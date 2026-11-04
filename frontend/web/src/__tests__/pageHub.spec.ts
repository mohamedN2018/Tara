import { createPinia, getActivePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, type Component, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import PageAbout from "@/components/pages/PageAbout.vue";
import PageHeader from "@/components/pages/PageHeader.vue";
import PageManageCard from "@/components/pages/PageManageCard.vue";
import PageSuggestionsRow from "@/components/pages/PageSuggestionsRow.vue";
import SearchabilitySetting from "@/components/settings/SearchabilitySetting.vue";
import PostCard from "@/components/post/PostCard.vue";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import {
  canManagePage,
  canPostAs,
  cleanContact,
  contactHref,
  invalidContactKeys,
  type Page,
  pageService,
  validatePageHandle,
} from "@/services/pages";
import { useAuthStore } from "@/stores/auth";
import { usePageDirectoryStore } from "@/stores/pageDirectory";

// Track T3: the Pages manager, the page header and posting as a page.

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

const page = (over: Partial<Page> = {}): Page => ({
  id: "11111111-1111-1111-1111-111111111111",
  handle: "nile_books",
  name: "Nile Books",
  category: "Bookshop",
  description: "Arabic and English books",
  location: "Cairo",
  status: "published",
  avatar_media_id: null,
  cover_media_id: null,
  contact: {},
  owner_account_id: "a",
  my_role: null,
  viewer_following: false,
  followers_count: 3,
  created_at: "2026-11-01T00:00:00Z",
  ...over,
});

async function flush() {
  for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mount(component: Component, props: Record<string, unknown>) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/pages/:handle", name: "page", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push("/pages/x");
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render: () => h(component, props) });
  app.use(getActivePinia()!).use(router).use(i18n);
  app.mount(host);
  await flush();
  return host;
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "en";
});
afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
});

describe("pages helpers", () => {
  it("checks handles like the server, reserved words included", () => {
    expect(validatePageHandle("nile_books")).toBe("ok");
    expect(validatePageHandle("ab")).toBe("invalid");
    expect(validatePageHandle("bad-handle")).toBe("invalid");
    expect(validatePageHandle("Manage")).toBe("reserved");
    expect(validatePageHandle("id")).toBe("invalid");
  });

  it("links only safe contact values", () => {
    expect(contactHref("website", "https://nile.example")).toBe("https://nile.example");
    expect(contactHref("website", "javascript:alert(1)")).toBeNull();
    expect(contactHref("email", "a@b.co")).toBe("mailto:a@b.co");
    expect(contactHref("phone", "+20 (100) 123")).toBe("tel:+20100123");
    expect(contactHref("whatsapp", "+20 100 123")).toBe("https://wa.me/20100123");
    expect(cleanContact({ website: " ", email: "a@b.co" })).toEqual({ email: "a@b.co" });
  });

  it("reads which contact fields the server refused", () => {
    expect(invalidContactKeys([{ field: "contact.website" }, { field: "name" }, { field: "contact" }])).toEqual(["website"]);
    expect(invalidContactKeys(undefined)).toEqual([]);
  });

  it("gates posting and managing by role", () => {
    expect(canPostAs(page({ my_role: "editor" }))).toBe(true);
    expect(canPostAs(page({ my_role: "editor", status: "draft" }))).toBe(false);
    expect(canPostAs(page({ my_role: "moderator" }))).toBe(false);
    expect(canPostAs(page())).toBe(false);
    expect(canManagePage(page({ my_role: "admin" }))).toBe(true);
    expect(canManagePage(page({ my_role: "editor" }))).toBe(false);
  });

  it("posts as the page with its id and public audience", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: { id: "p1" } } });
    await pageService.createPost("pid", { body: "hello", media_ids: ["m1"] });
    expect(post).toHaveBeenCalledWith("/posts/", { type: "image", audience: "public", media_ids: ["m1"], body: "hello", page_id: "pid" });
  });

  it("lists followed pages from graph's following rows", async () => {
    vi.spyOn(api, "get").mockResolvedValue({
      data: { data: { following: [{ target_id: "u1", target_type: "user" }, { target_id: "p1", target_type: "page" }] } },
    });
    expect(await pageService.followedIds()).toEqual(["p1"]);
  });
});

describe("page directory", () => {
  it("names page authors from GET /pages/?ids=", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: [page()], page: { next_cursor: null } } });
    const store = usePageDirectoryStore();
    expect(store.label(page().id)).toBe("…");
    await flush();
    await new Promise((r) => setTimeout(r, 60));
    await flush();
    expect(get).toHaveBeenCalledWith("/pages/", { params: { ids: page().id } });
    expect(store.label(page().id)).toBe("Nile Books");
  });
});

describe("PageHeader", () => {
  const base = { tab: "posts", saved: false, busyPhoto: "" };

  it("shows Follow and Report to a visitor, with the follower count", async () => {
    const el = await mount(PageHeader, { ...base, page: page() });
    expect(el.querySelector("[data-testid=page-name]")?.textContent).toContain("Nile Books");
    expect(el.querySelector("[data-testid=page-followers]")?.textContent).toContain("3 followers");
    expect(el.querySelector("[data-testid=page-follow]")).not.toBeNull();
    expect(el.querySelector("[data-testid=page-edit]")).toBeNull();
    expect(el.querySelector("[data-testid=page-create-post]")).toBeNull();
    expect(el.querySelector("[data-testid=page-tab-team]")).toBeNull();
    (el.querySelector("[data-testid=page-more]") as HTMLButtonElement).click();
    await flush();
    expect(el.querySelector("[data-testid=page-report]")).not.toBeNull();
    expect(el.querySelector("[data-testid=page-save]")?.textContent).toContain("Save page");
  });

  it("gives an editor Create post, Edit page, photo controls and the Team tab, but no Follow or Report", async () => {
    const el = await mount(PageHeader, { ...base, page: page({ my_role: "editor" }) });
    expect(el.querySelector("[data-testid=page-create-post]")).not.toBeNull();
    expect(el.querySelector("[data-testid=page-edit]")).not.toBeNull();
    expect(el.querySelector("[data-testid=page-edit-avatar]")).not.toBeNull();
    expect(el.querySelector("[data-testid=page-edit-cover]")).not.toBeNull();
    expect(el.querySelector("[data-testid=page-follow]")).toBeNull();
    expect(el.querySelector("[data-testid=page-tab-team]")).not.toBeNull();
    (el.querySelector("[data-testid=page-more]") as HTMLButtonElement).click();
    await flush();
    expect(el.querySelector("[data-testid=page-report]")).toBeNull();
  });

  it("hides the follower count and Follow when graph could not answer", async () => {
    const el = await mount(PageHeader, { ...base, page: page({ followers_count: null, viewer_following: null }) });
    expect(el.querySelector("[data-testid=page-followers]")).toBeNull();
    expect(el.querySelector("[data-testid=page-follow]")).toBeNull();
  });
});

describe("PageAbout", () => {
  it("renders safe contact links and drops unsafe ones as plain text", async () => {
    const el = await mount(PageAbout, {
      page: page({ contact: { website: "https://nile.example/", email: "hi@nile.example", x: "javascript:alert(1)" } }),
      full: true,
    });
    const links = [...el.querySelectorAll("[data-testid=page-contact] a")].map((a) => a.getAttribute("href"));
    expect(links).toEqual(["mailto:hi@nile.example", "https://nile.example/"]);
    expect(el.textContent).toContain("javascript:alert(1)");
    expect(el.querySelector("a[href^=javascript]")).toBeNull();
  });

  it("says so when the page has no details", async () => {
    const el = await mount(PageAbout, { page: page({ description: "", category: "", location: "" }) });
    expect(el.textContent).toContain("hasn't added any details");
  });
});

describe("PageManageCard", () => {
  it("offers Create post only to roles that may post", async () => {
    let el = await mount(PageManageCard, { page: page({ my_role: "owner" }) });
    expect(el.textContent).toContain("Create post");
    expect(el.textContent).toContain("Owner");
    app?.unmount();
    host?.remove();
    el = await mount(PageManageCard, { page: page({ my_role: "analyst" }) });
    expect(el.textContent).not.toContain("Create post");
    expect(el.textContent).toContain("View page");
  });
});

describe("PageHeader name in RTL", () => {
  it("keeps the heading in the page's direction and isolates only the name", async () => {
    const el = await mount(PageHeader, { tab: "posts", saved: false, busyPhoto: "", page: page() });
    const h1 = el.querySelector("[data-testid=page-name]")!;
    expect(h1.hasAttribute("dir")).toBe(false);
    expect(h1.querySelector("bdi")?.textContent).toBe("Nile Books");
  });
});

describe("PageSuggestionsRow", () => {
  const suggestion = (id: string, name: string) => ({
    page_id: id,
    handle: name.toLowerCase().replace(/ /g, "_"),
    name,
    category: "Books",
    avatar_media_id: null,
    followers_count: 4,
  });

  it("lists graph's suggestions and follows one", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: { results: [suggestion("p1", "Nile Books"), suggestion("p2", "Cairo Cafe")] } } });
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const el = await mount(PageSuggestionsRow, {});
    expect(api.get).toHaveBeenCalledWith("/social/suggestions/pages/", { params: { limit: 12 } });
    expect(el.querySelectorAll("[data-testid=pages-suggested-item]").length).toBe(2);
    expect(el.textContent).toContain("Suggested for you");
    (el.querySelector("[data-testid=pages-suggested-follow]") as HTMLButtonElement).click();
    await flush();
    expect(post).toHaveBeenCalledWith("/follows/p1/", { target_type: "page" });
    expect(el.querySelector("[data-testid=pages-suggested-followed]")).not.toBeNull();
    expect(el.textContent).toContain("5 followers");
  });

  it("removes a suggestion through graph's dismiss, with undo", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: { results: [suggestion("p1", "Nile Books")] } } });
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: {} });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: {} });
    const el = await mount(PageSuggestionsRow, {});
    (el.querySelector("[data-testid=pages-suggested-remove]") as HTMLButtonElement).click();
    await flush();
    expect(post).toHaveBeenCalledWith("/social/suggestions/p1/dismiss/", { target_type: "page" });
    expect(el.querySelector("[data-testid=pages-suggested-item]")).toBeNull();
    (el.querySelector("[data-testid=pages-suggested-undo]") as HTMLButtonElement).click();
    await flush();
    expect(del).toHaveBeenCalledWith("/social/suggestions/p1/dismiss/", { params: { target_type: "page" } });
    expect(el.querySelectorAll("[data-testid=pages-suggested-item]").length).toBe(1);
  });

  it("renders nothing when graph has no suggestions or is down", async () => {
    vi.spyOn(api, "get").mockRejectedValue(new Error("down"));
    const el = await mount(PageSuggestionsRow, {});
    expect(el.querySelector("[data-testid=pages-suggested]")).toBeNull();
  });
});

describe("SearchabilitySetting", () => {
  it("reads and turns off the searchable flag", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: { handle: "me", searchable: true } } });
    const patch = vi.spyOn(api, "patch").mockResolvedValue({ data: { data: { handle: "me", searchable: false } } });
    const el = await mount(SearchabilitySetting, {});
    const sw = el.querySelector("[data-testid=privacy-searchable-switch]") as HTMLButtonElement;
    expect(sw.getAttribute("aria-checked")).toBe("true");
    sw.click();
    await flush();
    expect(patch).toHaveBeenCalledWith("/profile/me/", { searchable: false });
    expect(sw.getAttribute("aria-checked")).toBe("false");
  });

  it("says so when the profile can't be loaded", async () => {
    vi.spyOn(api, "get").mockRejectedValue(new Error("down"));
    const el = await mount(SearchabilitySetting, {});
    expect(el.querySelector("[data-testid=privacy-searchable-switch]")).toBeNull();
    expect(el.textContent).toContain("can't be loaded");
  });
});

describe("PostCard on a page's timeline", () => {
  const pagePost = {
    id: "pp1",
    author_id: "11111111-1111-1111-1111-111111111111",
    author_type: "page",
    type: "text",
    body: "From the page",
    audience: "public",
    media_ids: [],
    reaction_count: 0,
    comment_count: 0,
    share_count: 0,
    created_at: "2026-11-03T10:00:00Z",
  };

  async function mountCard(props: Record<string, unknown>) {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/pages/id/:id", name: "page-by-id", component: Blank },
        { path: "/posts/:id", name: "post", component: Blank },
        { path: "/:rest(.*)*", component: Blank },
      ],
    });
    await router.push("/pages/x");
    await router.isReady();
    host = document.createElement("div");
    document.body.appendChild(host);
    app = createApp({ render: () => h(PostCard, { post: pagePost, authorName: "Nile Books", ...props }) });
    app.use(getActivePinia()!).use(router).use(i18n);
    app.mount(host);
    await flush();
    (host.querySelector("[data-testid=post-menu]") as HTMLElement).click();
    await flush();
    return host;
  }

  beforeEach(() => {
    useAuthStore().account = { id: "me-1", email: "me@example.com" } as never;
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: [], page: { next_cursor: null, has_more: false } } });
  });

  it("offers Edit to the page's owners, admins and editors", async () => {
    const el = await mountCard({ pageEditor: true, pageModerator: true });
    expect(el.querySelector("[data-testid=menu-edit]")).not.toBeNull();
  });

  it("offers no Edit to other roles or visitors", async () => {
    const el = await mountCard({ pageEditor: false, pageModerator: true });
    expect(el.querySelector("[data-testid=menu-edit]")).toBeNull();
  });
});
