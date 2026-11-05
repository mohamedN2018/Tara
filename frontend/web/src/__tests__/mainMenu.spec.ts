import { Home } from "lucide-vue-next";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it } from "vitest";
import { type App, createApp, defineComponent, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import MainMenu from "@/components/layout/MainMenu.vue";

import {
  CONSOLE_CAPS,
  CREATE_CATALOG,
  MENU_CATALOG,
  MENU_CATEGORIES,
  type MenuItem,
  createItems,
  filterCreate,
  filterSections,
  foldText,
  hasItem,
  menuSections,
  SELF_PROFILE,
} from "@/components/layout/menuCatalog";
import { handleMenuKey, menuItems, nextMenuIndex } from "@/components/layout/menuKeyboard";
import { i18n } from "@/i18n";
import ar from "@/i18n/ar";
import en from "@/i18n/en";
import { router } from "@/router";
import { useAuthStore } from "@/stores/auth";

const ids = (caps: string[] = [], type: "personal" | "creator" | "business" = "personal") =>
  menuSections(caps, type).flatMap((s) => s.items.map((i) => i.id));

function lookup(locale: object, key: string): unknown {
  return key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], locale);
}

describe("menu catalogue", () => {
  it("shows a plain member no staff item", () => {
    const visible = ids();
    expect(visible).not.toContain("admin");
    expect(visible).not.toContain("adReview");
    expect(visible).toEqual(expect.arrayContaining(["home", "friends", "marketplace", "groups", "events", "settings"]));
  });

  it("shows staff items only to the capability that opens them", () => {
    expect(ids(["ads.review"])).toContain("adReview");
    expect(ids(["ads.review"])).not.toContain("admin");
    expect(ids(["moderation.case.view"])).toContain("admin");
    expect(ids(["admin.audit.view"])).toContain("admin");
    expect(ids(["admin.audit.view"])).not.toContain("adReview");
  });

  it("hides every unbuilt module, and categories left empty", () => {
    const all = ids([...CONSOLE_CAPS, "ads.review"]);
    for (const item of MENU_CATALOG.filter((i) => !i.built)) expect(all).not.toContain(item.id);
    expect(all).not.toContain("memories");
    // Reels are built (5.8): a destination of their own, apart from Videos.
    expect(all).toContain("reels");
    expect(all).toContain("videos");
    const categories = menuSections([]).map((s) => s.category);
    // The creator studio is built (T8) with its insights; monetization stays hidden.
    expect(categories).toContain("creator");
    expect(all).toContain("analytics");
    expect(all).not.toContain("monetization");
    expect(categories).not.toContain("professional");
    // The rest keep the spec's order.
    expect(categories).toEqual(MENU_CATEGORIES.filter((c) => categories.includes(c)));
  });

  it("filters by account type", () => {
    const catalog: MenuItem[] = [
      { id: "everyone", route: "/home", labelKey: "nav.home", icon: Home, category: "social", built: true },
      { id: "creatorOnly", route: "/home", labelKey: "nav.home", icon: Home, category: "creator", accountTypes: ["creator"], built: true },
      { id: "creatorUnbuilt", route: "/home", labelKey: "nav.home", icon: Home, category: "creator", accountTypes: ["creator"], built: false },
    ];
    const personal = menuSections([], "personal", { catalog }).flatMap((s) => s.items.map((i) => i.id));
    const creator = menuSections([], "creator", { catalog }).flatMap((s) => s.items.map((i) => i.id));
    expect(personal).toEqual(["everyone"]);
    expect(creator).toEqual(["everyone", "creatorOnly"]);
  });

  it("resolves the own-profile entry to the account's profile", () => {
    const [account] = menuSections([], "personal", { profile: "/u/laila" });
    expect(account.items.find((i) => i.id === "profile")?.to).toBe("/u/laila");
  });

  it("points every built item and create flow at a real route", () => {
    const built = [...MENU_CATALOG.filter((i) => i.built && i.route !== SELF_PROFILE), ...CREATE_CATALOG];
    for (const item of built) {
      const resolved = router.resolve(item.route as Parameters<typeof router.resolve>[0]);
      expect(resolved.name, `${item.id} -> ${resolved.fullPath}`).not.toBe("not-found");
    }
  });

  it("gates each staff item at least as tightly as its route", () => {
    for (const item of MENU_CATALOG.filter((i) => i.built && i.route !== SELF_PROFILE)) {
      const meta = router.resolve(item.route as Parameters<typeof router.resolve>[0]).meta;
      if (meta.staff) expect(item.caps?.every((c) => CONSOLE_CAPS.includes(c)), item.id).toBe(true);
      if (meta.caps) expect(item.caps, item.id).toEqual(meta.caps);
      if (!meta.staff && !meta.caps) expect(item.caps, item.id).toBeUndefined();
    }
  });

  it("only offers creation flows that exist", () => {
    expect(createItems([]).map((i) => i.id)).toEqual(["post", "story", "reel", "page", "group", "event", "listing"]);
  });

  it("has every label in both languages", () => {
    const keys = [
      ...MENU_CATALOG.flatMap((i) => [i.labelKey, i.descKey].filter(Boolean) as string[]),
      ...CREATE_CATALOG.map((i) => i.labelKey),
      ...MENU_CATEGORIES.map((c) => `menu.sections.${c}`),
    ];
    for (const key of keys) {
      expect(typeof lookup(ar, key), `ar ${key}`).toBe("string");
      expect(typeof lookup(en, key), `en ${key}`).toBe("string");
    }
  });

  it("keeps help & support hidden until the help centre is built", () => {
    expect(hasItem("helpCenter", [])).toBe(false);
    expect(hasItem("settings", [])).toBe(true);
    expect(hasItem("admin", [])).toBe(false);
    expect(hasItem("admin", ["admin.users.view"])).toBe(true);
  });
});

describe("search in the menu", () => {
  const translate = (key: string) => String(lookup(ar, key) ?? key);

  it("folds Arabic spelling variants and diacritics", () => {
    expect(foldText("الإعدادات")).toBe(foldText("الاعدادات"));
    expect(foldText("فعّالية")).toBe(foldText("فعاليه"));
    expect(foldText("Marketplace")).toBe("marketplace");
  });

  it("keeps the matching items and drops empty sections", () => {
    const sections = filterSections(menuSections([]), "الاعدادات", translate);
    expect(sections.map((s) => s.category)).toEqual(["system"]);
    expect(sections[0].items.map((i) => i.id)).toEqual(["settings"]);
    expect(filterSections(menuSections([]), "zzz-nothing", translate)).toEqual([]);
    expect(filterSections(menuSections([]), "  ", translate)).toEqual(menuSections([]));
  });

  it("filters the Create column too", () => {
    expect(filterCreate(createItems([]), "مجموعة", translate).map((i) => i.id)).toEqual(["group"]);
  });

  it("matches English labels", () => {
    const translateEn = (key: string) => String(lookup(en, key) ?? key);
    const sections = filterSections(menuSections([]), "sell", translateEn);
    expect(sections.flatMap((s) => s.items.map((i) => i.id))).toEqual(["marketplace", "myListings"]);
  });
});

describe("menu keyboard", () => {
  it("wraps around and jumps with Home/End", () => {
    expect(nextMenuIndex(-1, 3, "ArrowDown")).toBe(0);
    expect(nextMenuIndex(-1, 3, "ArrowUp")).toBe(2);
    expect(nextMenuIndex(2, 3, "ArrowDown")).toBe(0);
    expect(nextMenuIndex(0, 3, "ArrowUp")).toBe(2);
    expect(nextMenuIndex(1, 3, "Home")).toBe(0);
    expect(nextMenuIndex(1, 3, "End")).toBe(2);
    expect(nextMenuIndex(1, 3, "a")).toBeNull();
    expect(nextMenuIndex(-1, 0, "ArrowDown")).toBeNull();
  });

  function panel() {
    document.body.innerHTML = `
      <div id="panel">
        <input id="q" type="search" />
        <div role="menu">
          <div role="group" aria-label="Social">
            <a id="a" role="menuitem" tabindex="-1" href="/home">Home</a>
            <a id="b" role="menuitem" tabindex="-1" href="/friends">Friends</a>
          </div>
        </div>
        <div role="menu">
          <a id="c" role="menuitem" tabindex="-1" href="/groups/new">Group</a>
        </div>
      </div>`;
    return document.getElementById("panel") as HTMLElement;
  }
  const key = (root: HTMLElement, k: string) => handleMenuKey(root, { key: k, target: document.activeElement });

  it("moves from the search field into the items, across both columns", () => {
    const root = panel();
    (document.getElementById("q") as HTMLInputElement).focus();
    expect(key(root, "ArrowDown")).toBe(true);
    expect(document.activeElement?.id).toBe("a");
    key(root, "ArrowDown");
    expect(document.activeElement?.id).toBe("b");
    key(root, "ArrowDown");
    expect(document.activeElement?.id).toBe("c");
    key(root, "ArrowDown");
    expect(document.activeElement?.id).toBe("a");
    key(root, "ArrowUp");
    expect(document.activeElement?.id).toBe("c");
    key(root, "Home");
    expect(document.activeElement?.id).toBe("a");
    key(root, "End");
    expect(document.activeElement?.id).toBe("c");
  });

  it("keeps a single item in the Tab order", () => {
    const root = panel();
    (document.getElementById("q") as HTMLInputElement).focus();
    key(root, "ArrowDown");
    key(root, "ArrowDown");
    expect(menuItems(root).map((el) => el.getAttribute("tabindex"))).toEqual(["-1", "0", "-1"]);
  });

  it("leaves Home/End and other keys to the search field", () => {
    const root = panel();
    (document.getElementById("q") as HTMLInputElement).focus();
    expect(key(root, "Home")).toBe(false);
    expect(key(root, "x")).toBe(false);
    expect(document.activeElement?.id).toBe("q");
  });

  it("skips disabled items", () => {
    const root = panel();
    document.getElementById("b")?.setAttribute("aria-disabled", "true");
    expect(menuItems(root).map((el) => el.id)).toEqual(["a", "c"]);
  });
});

describe("MainMenu component", () => {
  let app: App | null = null;
  afterEach(() => {
    app?.unmount();
    app = null;
    document.body.innerHTML = "";
  });

  async function mountMenu(caps: string[] = []) {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.capabilities = new Set(caps);
    i18n.global.locale.value = "ar";
    const Blank = defineComponent({ render: () => null });
    const memory = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", component: Blank }] });
    await memory.push("/home");
    const host = document.createElement("div");
    document.body.appendChild(host);
    app = createApp(MainMenu).use(pinia).use(memory).use(i18n);
    app.mount(host);
    const trigger = document.querySelector<HTMLButtonElement>('[data-testid="main-menu-button"]')!;
    trigger.click();
    await nextTick();
    await nextTick();
    return trigger;
  }
  const press = (key: string) =>
    (document.activeElement as HTMLElement).dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  const focused = () => (document.activeElement as HTMLElement | null)?.dataset.testid;

  it("opens on the search field, arrows through the entries and Escape returns focus", async () => {
    const trigger = await mountMenu();
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(focused()).toBe("main-menu-search");
    press("ArrowDown");
    expect(focused()).toBe("menu-item-profile");
    press("ArrowDown");
    expect(focused()).toBe("menu-item-friends");
    press("ArrowUp");
    press("ArrowUp");
    expect(focused()).toBe("menu-create-listing");
    press("Escape");
    await nextTick();
    expect(document.querySelector('[data-testid="main-menu"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("renders no staff entry without a capability, and the console entry with one", async () => {
    await mountMenu();
    expect(document.querySelector('[data-testid="menu-item-admin"]')).toBeNull();
    expect(document.querySelector('[data-testid="menu-item-adReview"]')).toBeNull();
    expect(document.querySelectorAll('[role="menuitem"][aria-disabled], [role="menuitem"][disabled]')).toHaveLength(0);
    app?.unmount();
    document.body.innerHTML = "";
    await mountMenu(["moderation.case.view"]);
    expect(document.querySelector('[data-testid="menu-item-admin"]')).not.toBeNull();
  });
});
