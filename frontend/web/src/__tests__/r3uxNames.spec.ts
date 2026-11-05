// Fix round 3, track r3-ux: the remaining page and group names keep the UI's
// direction (start-aligned in Arabic, the name alone in a <bdi>, as
// PageHeader does), and a member's message to Tara Support reads as such for
// the support team that is notified of it.
import { createPinia, getActivePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, type Component, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import RailPageSuggestions from "@/components/layout/RailPageSuggestions.vue";
import NotificationItem from "@/components/notifications/NotificationItem.vue";
import { iconFor, notificationExcerpt, notificationText, urlFor } from "@/components/notifications/kinds";
import GroupResult from "@/components/search/GroupResult.vue";
import PageResult from "@/components/search/PageResult.vue";
import { i18n } from "@/i18n";
import { relationshipsService } from "@/services/relationships";
import type { SearchResult } from "@/services/search";
import { useDirectoryStore } from "@/stores/directory";
import type { Notification } from "@/types";

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

async function mount(component: Component, props: Record<string, unknown> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/pages/:handle", name: "page", component: Blank },
      { path: "/pages", name: "pages", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push("/x");
  await router.isReady();
  host = document.createElement("div");
  host.setAttribute("dir", "rtl");
  document.body.appendChild(host);
  app = createApp({ render: () => h(component, props) });
  app.use(getActivePinia()!).use(router).use(i18n);
  app.mount(host);
  for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0));
  return host;
}

beforeEach(() => {
  setActivePinia(createPinia());
  i18n.global.locale.value = "ar";
});
afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
  i18n.global.locale.value = "en";
});

function expectIsolated(el: HTMLElement, testid: string, name: string) {
  const block = el.querySelector(`[data-testid=${testid}]`)!;
  expect(block, testid).not.toBeNull();
  expect(block.hasAttribute("dir")).toBe(false); // inherits rtl: stays at the start edge
  expect(block.querySelector("bdi")?.textContent?.trim()).toBe(name);
}

const result = (over: Partial<SearchResult>): SearchResult =>
  ({ type: "page", id: "p1", title: "", snippet: "", owner_id: null, ...over }) as SearchResult;

describe("page and group names in search and the right rail (Arabic UI)", () => {
  it("a page search result isolates only the name", async () => {
    const el = await mount(PageResult, { result: result({ name: "Cairo Jazz Club", handle: "cjc", followers_count: 4 } as Partial<SearchResult>) });
    expectIsolated(el, "page-result-name", "Cairo Jazz Club");
  });

  it("a group search result isolates only the name", async () => {
    const el = await mount(GroupResult, { result: result({ type: "group", name: "Alex Makers", handle: "alex", privacy: "public" } as Partial<SearchResult>) });
    expectIsolated(el, "group-result-name", "Alex Makers");
  });

  it("the rail's suggested pages isolate only the name", async () => {
    vi.spyOn(relationshipsService, "pages").mockResolvedValue([
      { page_id: "p1", handle: "nile", name: "Nile Books", category: "", avatar_media_id: null, followers_count: 2 },
    ]);
    const el = await mount(RailPageSuggestions);
    expectIsolated(el, "rail-page-name", "Nile Books");
  });
});

function support(over: Partial<Notification> = {}): Notification {
  return {
    id: "n9",
    kind: "message.support",
    category: "messages",
    actor_id: "sam",
    actor_count: 1,
    subject_ref: "conversation:c9",
    body: "locked out?",
    read_at: null,
    created_at: "2026-11-05T10:00:00Z",
    last_event_at: "2026-11-05T10:00:00Z",
    url: "/admin/support?conversation=c9",
    data: { conversation_id: "c9" },
    ...over,
  } as unknown as Notification;
}

const t = i18n.global.t as unknown as (k: string, n?: Record<string, unknown>, p?: number) => string;
const te = (k: string) => i18n.global.te(k);

describe("a member's message to Tara Support, for the support team", () => {
  it("names the member and Tara Support, quotes one message, and opens the support inbox", () => {
    i18n.global.locale.value = "en";
    expect(notificationText(support(), t, te, "Sam")).toBe("Sam to Tara Support: locked out?");
    expect(notificationText(support({ body: "" }), t, te, "Sam")).toBe("Sam sent Tara Support a message");
    expect(notificationText(support({ data: { conversation_id: "c9", message_count: 3 } }), t, te, "Sam")).toBe(
      "Sam sent Tara Support 3 messages",
    );
    expect(notificationExcerpt(support())).toBe("locked out?");
    expect(notificationExcerpt(support({ data: { message_count: 2 } }))).toBe("");
    expect(urlFor(support())).toBe("/admin/support?conversation=c9");
    expect(iconFor("message.support")).toBe(iconFor("message"));
  });

  it("isolates the member's name and the English text in the Arabic UI", async () => {
    useDirectoryStore().remember("sam", "ليلى", null);
    const el = await mount(NotificationItem, { notification: support() });
    const p = el.querySelector("[data-testid=notification-text]")!;
    expect(p.hasAttribute("dir")).toBe(false);
    expect([...p.querySelectorAll("bdi")].map((b) => b.textContent)).toEqual(["ليلى", "locked out?"]);
    expect(p.textContent).toContain("دعم تارا");
  });

  it("has a Settings label in both languages", () => {
    i18n.global.locale.value = "en";
    expect(t("settings.notif.message_support")).toBe("Messages to Tara Support");
    i18n.global.locale.value = "ar";
    expect(te("settings.notif.message_support")).toBe(true);
  });
});
