import { createPinia, getActivePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { type App, type Component, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import GroupCard from "@/components/groups/GroupCard.vue";
import GroupHeader from "@/components/groups/GroupHeader.vue";
import PageListItem from "@/components/pages/PageListItem.vue";
import PageManageCard from "@/components/pages/PageManageCard.vue";
import { i18n } from "@/i18n";
import type { Group, GroupCan } from "@/services/groups";
import type { Page } from "@/services/pages";

// Fix round 3, track C: a Latin page or group name in the Arabic UI keeps the
// block in the UI's direction (so it stays at the start edge, next to the
// avatar) and isolates only the name in a <bdi>, as PageHeader does. A block
// with dir="auto" would flip to LTR and sit on the far edge.

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

const page = (over: Partial<Page> = {}): Page => ({
  id: "11111111-1111-1111-1111-111111111111",
  handle: "nile_books",
  name: "Nile Books",
  category: "Bookshop",
  description: "",
  location: "Cairo",
  status: "published",
  avatar_media_id: null,
  cover_media_id: null,
  contact: {},
  owner_account_id: "a",
  my_role: "owner",
  viewer_following: false,
  followers_count: 3,
  created_at: "2026-11-01T00:00:00Z",
  ...over,
});

const NO_CAN: GroupCan = {
  post: false,
  invite: false,
  edit: false,
  delete: false,
  change_privacy: false,
  manage_rules: false,
  approve_requests: false,
  approve_posts: false,
  moderate: false,
  change_roles: false,
  pin: false,
  view_reports: false,
};

const group = (over: Partial<Group> = {}): Group => ({
  id: "g1",
  handle: "alex_makers",
  name: "Alex Makers",
  description: "",
  category: "general",
  privacy: "public",
  membership_approval: false,
  post_approval: false,
  cover_media_id: null,
  member_count: 3,
  created_at: "2026-11-01T10:00:00Z",
  updated_at: "2026-11-01T10:00:00Z",
  content_visible: true,
  viewer: { role: null, state: null, notify_posts: false, can: { ...NO_CAN } },
  ...over,
});

async function mount(component: Component, props: Record<string, unknown>) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/pages/:handle", name: "page", component: Blank },
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
  for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0));
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
  i18n.global.locale.value = "en";
});

function expectIsolated(el: HTMLElement, testid: string, name: string) {
  const block = el.querySelector(`[data-testid=${testid}]`)!;
  expect(block, testid).not.toBeNull();
  expect(block.hasAttribute("dir")).toBe(false); // inherits rtl: start-aligned
  expect(block.querySelector("bdi")?.textContent?.trim()).toBe(name);
}

describe("page and group names in the Arabic UI", () => {
  it("PageManageCard isolates only the name", async () => {
    expectIsolated(await mount(PageManageCard, { page: page() }), "page-card-name", "Nile Books");
  });

  it("PageListItem isolates only the name", async () => {
    expectIsolated(await mount(PageListItem, { page: page({ name: "Cairo Jazz Club", category: "" }) }), "page-list-name", "Cairo Jazz Club");
  });

  it("GroupCard isolates only the name", async () => {
    expectIsolated(await mount(GroupCard, { group: group() }), "group-card-name", "Alex Makers");
  });

  it("GroupHeader keeps the heading in the UI's direction", async () => {
    const el = await mount(GroupHeader, { group: group() });
    const h1 = el.querySelector("#group-title")!;
    expect(h1.getAttribute("data-testid")).toBe("group-name");
    expect(h1.hasAttribute("dir")).toBe(false);
    expect(h1.querySelector("bdi")?.textContent).toBe("Alex Makers");
  });
});
