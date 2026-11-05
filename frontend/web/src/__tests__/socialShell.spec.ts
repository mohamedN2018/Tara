import { createPinia, getActivePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, type Component, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import RailBirthdays from "@/components/layout/RailBirthdays.vue";
import { DROPDOWN_PAGE, dropdownRows, NEW_WINDOW_MS, splitByRecency } from "@/components/notifications/dropdownSections";
import NotificationPanel from "@/components/notifications/NotificationPanel.vue";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { birthdayDate, localDate, splitBirthdays } from "@/services/birthdays";
import { groupPostsService } from "@/services/groups";
import { notificationService } from "@/services/notification";
import { useDirectoryStore } from "@/stores/directory";
import type { Notification } from "@/types";
import FriendsView from "@/views/FriendsView.vue";
import GroupsView from "@/views/GroupsView.vue";

// Social shell track: Friends home and birthdays, the right column's birthdays
// card, the groups Join / View group buttons and rail, and the notifications
// dropdown's chips, sections and "See previous".

vi.mock("@/components/layout/AppShell.vue", () => ({
  default: defineComponent({ setup: (_, { slots }) => () => h("div", slots.default?.()) }),
}));

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

const empty = { data: { data: [], page: { next_cursor: null, prev_cursor: null, has_more: false } } };
type Get = (url: string, config?: { params?: Record<string, unknown> }) => unknown;
function mockGet(handler: Get) {
  return vi.spyOn(api, "get").mockImplementation(async (url: string, config?: unknown) => {
    const out = handler(url, config as { params?: Record<string, unknown> });
    return (out ?? empty) as never;
  });
}

async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mount(component: Component, path = "/x", props: Record<string, unknown> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/u/id/:id", name: "profile-by-id", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push(path);
  await router.isReady();
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render: () => h(component, props) });
  app.use(getActivePinia()!).use(router).use(i18n);
  app.mount(host);
  await flush();
  return { el: host, router };
}

const q = (el: ParentNode, id: string) => el.querySelector<HTMLElement>(`[data-testid="${id}"]`);
const qa = (el: ParentNode, id: string) => [...el.querySelectorAll<HTMLElement>(`[data-testid="${id}"]`)];

function notif(over: Partial<Notification> = {}): Notification {
  return {
    id: "n1",
    kind: "post.liked",
    category: "social",
    actor_id: "u1",
    subject_ref: "post:p1",
    body: "",
    read_at: null,
    created_at: new Date().toISOString(),
    url: "/posts/p1",
    ...over,
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.clear();
  i18n.global.locale.value = "en";
  vi.spyOn(api, "post").mockResolvedValue({ data: { data: {} } });
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  vi.restoreAllMocks();
});

describe("notification dropdown helpers", () => {
  it("splits rows into New (the last day) and Earlier, keeping their order", () => {
    const now = Date.parse("2026-11-05T12:00:00Z");
    const rows = [
      notif({ id: "a", created_at: "2026-11-05T11:00:00Z" }),
      notif({ id: "b", created_at: "2026-11-01T00:00:00Z", last_event_at: "2026-11-05T10:00:00Z" }),
      notif({ id: "c", created_at: new Date(now - NEW_WINDOW_MS - 1).toISOString() }),
      notif({ id: "d", created_at: "not a date" }),
    ];
    const { fresh, earlier } = splitByRecency(rows, now);
    expect(fresh.map((n) => n.id)).toEqual(["a", "b"]);
    expect(earlier.map((n) => n.id)).toEqual(["c", "d"]);
  });

  it("Unread keeps rows that were unread when switched on", () => {
    const rows = [notif({ id: "a" }), notif({ id: "b", read_at: "x" }), notif({ id: "c", read_at: "x" })];
    expect(dropdownRows(rows, false, new Set()).map((n) => n.id)).toEqual(["a", "b", "c"]);
    expect(dropdownRows(rows, true, new Set(["b"])).map((n) => n.id)).toEqual(["a", "b"]);
  });
});

describe("notification dropdown", () => {
  it("has All / Unread chips, New / Earlier sections and See previous loading the next page", async () => {
    const recent = new Date().toISOString();
    const old = "2026-01-01T10:00:00Z";
    const first = Array.from({ length: DROPDOWN_PAGE }, (_, i) =>
      notif({ id: `p1-${i}`, created_at: i < 2 ? recent : old, read_at: i % 2 ? "2026-01-02T00:00:00Z" : null }),
    );
    const second = [notif({ id: "p2-0", created_at: old }), notif({ id: "p2-1", created_at: old, read_at: "x" })];
    const list = vi.spyOn(notificationService, "list").mockImplementation(async (opts) => {
      const cursor = typeof opts === "object" ? opts.cursor : opts;
      if (cursor === "c2") return { data: second, page: { next_cursor: null, prev_cursor: null, has_more: false } };
      return { data: first, page: { next_cursor: "c2", prev_cursor: null, has_more: true } };
    });
    vi.spyOn(notificationService, "unreadCount").mockResolvedValue(5);
    mockGet(() => undefined);

    const { el } = await mount(NotificationPanel);
    expect(q(el, "notif-dropdown-filter-all")?.getAttribute("aria-pressed")).toBe("true");
    const newRows = q(el, "notif-dropdown-section-new")!;
    expect(newRows.querySelector("h4")?.textContent?.trim()).toBe("New");
    expect(newRows.querySelectorAll("li")).toHaveLength(2);
    expect(q(el, "notif-dropdown-section-earlier")?.querySelectorAll("li")).toHaveLength(DROPDOWN_PAGE - 2);

    q(el, "notif-dropdown-see-previous")!.click();
    await flush();
    expect(list).toHaveBeenCalledWith({ cursor: "c2" });
    expect(el.querySelectorAll("li")).toHaveLength(DROPDOWN_PAGE + 2);
    // Everything is loaded and shown: no more "See previous".
    expect(q(el, "notif-dropdown-see-previous")).toBeNull();

    q(el, "notif-dropdown-filter-unread")!.click();
    await flush();
    expect(q(el, "notif-dropdown-filter-unread")?.getAttribute("aria-pressed")).toBe("true");
    const shown = [...el.querySelectorAll("li")].length;
    expect(shown).toBe(first.filter((n) => !n.read_at).length + 1);
  });

  it("says when nothing is unread", async () => {
    vi.spyOn(notificationService, "list").mockResolvedValue({
      data: [notif({ read_at: "x" })],
      page: { next_cursor: null, prev_cursor: null, has_more: false },
    });
    vi.spyOn(notificationService, "unreadCount").mockResolvedValue(0);
    mockGet(() => undefined);
    const { el } = await mount(NotificationPanel);
    q(el, "notif-dropdown-filter-unread")!.click();
    await flush();
    expect(el.textContent).toContain(i18n.global.t("notifications.emptyUnread"));
  });
});

describe("birthdays", () => {
  it("formats day and month only, in both languages, and splits today from this week", () => {
    expect(localDate(new Date(2026, 0, 5))).toBe("2026-01-05");
    expect(birthdayDate({ month: 2, day: 29 }, "en")).toBe("February 29");
    expect(birthdayDate({ month: 11, day: 5 }, "ar")).toMatch(/نوفمبر/);
    const rows = [
      { account_id: "a", month: 1, day: 1, days_until: 0 },
      { account_id: "b", month: 1, day: 3, days_until: 2 },
    ];
    expect(splitBirthdays(rows).today.map((r) => r.account_id)).toEqual(["a"]);
    expect(splitBirthdays(rows).upcoming.map((r) => r.account_id)).toEqual(["b"]);
  });

  it("the right column names today's birthdays and links to Friends > Birthdays", async () => {
    const get = mockGet((url) =>
      url === "/me/birthdays/"
        ? {
            data: {
              data: {
                date: "2026-11-05",
                days: 1,
                results: [
                  { account_id: "a", month: 11, day: 5, days_until: 0 },
                  { account_id: "b", month: 11, day: 5, days_until: 0 },
                  { account_id: "c", month: 11, day: 5, days_until: 0 },
                ],
              },
            },
          }
        : undefined,
    );
    const directory = useDirectoryStore();
    vi.spyOn(directory, "label").mockImplementation((id?: string | null) => ({ a: "Sara", b: "Omar", c: "Mona" })[id ?? ""] ?? "");
    const { el } = await mount(RailBirthdays);
    expect(get).toHaveBeenCalledWith("/me/birthdays/", { params: { date: localDate(), days: 1 } });
    const link = q(el, "rail-birthdays-link")!;
    expect(link.getAttribute("href")).toBe("/friends?tab=birthdays");
    expect(link.textContent?.replace(/\s+/g, " ").trim()).toBe("Sara and 2 other friends have birthdays today.");
    expect(link.querySelector("bdi")?.textContent).toBe("Sara");
  });

  it("the right column stays hidden when nobody has a birthday today or identity fails", async () => {
    vi.spyOn(api, "get").mockRejectedValue(new Error("503"));
    const { el } = await mount(RailBirthdays);
    expect(q(el, "rail-birthdays")).toBeNull();
  });
});

describe("friends hub", () => {
  function friendsApi(birthdays: unknown[] = []) {
    return mockGet((url, config) => {
      if (url === "/friends/requests/" && !config?.params?.direction) {
        return {
          data: {
            data: [{ id: "r1", account_low_id: "me", account_high_id: "u9", status: "pending", requested_by: "u9", created_at: "2026-11-01T00:00:00Z", accepted_at: null }],
          },
        };
      }
      if (url === "/friends/requests/") return { data: { data: [] } };
      if (url === "/friends/") return { data: { data: { friends: ["f1"] } } };
      if (url === "/social/suggestions/") return { data: { data: { results: [{ account_id: "s1", mutual_count: 2, reason: "mutual_friends" }] } } };
      if (url === "/me/birthdays/") return { data: { data: { date: "2026-11-05", days: 7, results: birthdays } } };
      return undefined;
    });
  }

  it("opens on Home: the pending requests above People you may know", async () => {
    friendsApi();
    const { el } = await mount(FriendsView, "/friends");
    expect(q(el, "friends-tab-home")?.getAttribute("aria-current")).toBe("page");
    expect(q(el, "friends-home-requests")).not.toBeNull();
    expect(qa(el, "friend-request-card").map((c) => c.dataset.accountId)).toEqual(["u9"]);
    expect(qa(el, "friend-suggestion-card").map((c) => c.dataset.accountId)).toEqual(["s1"]);
    expect(q(el, "friend-suggestion-card")?.querySelector('[data-testid="person-photo"]')).not.toBeNull();

    q(el, "friends-home-requests-all")!.click();
    await flush();
    expect(q(el, "friends-tab-requests")?.getAttribute("aria-current")).toBe("page");
  });

  it("Birthdays lists today and this week from identity, with a message button", async () => {
    const get = friendsApi([
      { account_id: "f1", month: 11, day: 5, days_until: 0 },
      { account_id: "f2", month: 11, day: 8, days_until: 3 },
    ]);
    const { el } = await mount(FriendsView, "/friends?tab=birthdays");
    expect(get).toHaveBeenCalledWith("/me/birthdays/", { params: { date: localDate(), days: 7 } });
    expect(q(el, "birthdays-today")?.querySelectorAll('[data-testid="birthday-row"]')).toHaveLength(1);
    expect(q(el, "birthdays-upcoming")?.querySelectorAll('[data-testid="birthday-row"]')).toHaveLength(1);
    expect(q(el, "birthdays-today")?.textContent).toContain("Today");
    expect(qa(el, "birthday-message")).toHaveLength(2);
  });

  it("Birthdays says so when there are none", async () => {
    friendsApi([]);
    const { el } = await mount(FriendsView, "/friends?tab=birthdays");
    expect(el.textContent).toContain(i18n.global.t("socialShell.birthdays.none"));
  });
});

describe("groups", () => {
  const group = (id: string, over: Record<string, unknown> = {}) => ({
    id,
    handle: id,
    name: `Group ${id}`,
    description: "",
    category: "general",
    privacy: "public",
    membership_approval: false,
    post_approval: false,
    cover_media_id: null,
    member_count: 3,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    content_visible: true,
    viewer: { role: null, state: "none", notify_posts: false, can: {} },
    ...over,
  });
  const pageOf = (data: unknown[]) => ({ data: { data, page: { next_cursor: null, prev_cursor: null, has_more: false } } });
  const joined = { role: "member", state: "active", notify_posts: false, can: {} };

  function groupsApi() {
    return mockGet((url, config) => {
      if (url === "/groups/" && config?.params?.scope === "mine") {
        return pageOf([group("cats", { viewer: joined }), group("dogs", { viewer: joined }), group("hidden", { viewer: joined, content_visible: false })]);
      }
      if (url === "/groups/" && config?.params?.scope === "discover") return pageOf([group("chess")]);
      if (url === "/groups/suggestions/") return { data: { data: [group("bikes", { membership_approval: true })] } };
      return undefined;
    });
  }

  it("Discover and Suggested cards can be joined; Your groups cards open the group", async () => {
    groupsApi();
    vi.spyOn(groupPostsService, "activity").mockResolvedValue({});
    const { el } = await mount(GroupsView, "/groups?tab=discover");
    const cards = qa(el, "group-join");
    expect(cards).toHaveLength(2); // one suggestion, one browse result
    expect(cards[0].textContent).toContain(i18n.global.t("groups.join.request"));
    expect(cards[1].textContent).toContain(i18n.global.t("groups.join.join"));

    el.querySelector<HTMLElement>("#groups-tab-mine")!.click();
    await flush();
    const links = qa(el, "group-view-link");
    expect(links.length).toBeGreaterThan(0);
    expect(links[0].textContent).toContain("View group");
  });

  it("the rail searches my groups and shows when each last had a post", async () => {
    groupsApi();
    const activity = vi.spyOn(groupPostsService, "activity").mockResolvedValue({ cats: "2026-11-04T10:00:00Z", dogs: null });
    const { el } = await mount(GroupsView, "/groups");
    // Only groups whose posts may be read are asked about.
    expect(activity).toHaveBeenCalledWith(["cats", "dogs"]);
    expect(qa(el, "groups-rail-item")).toHaveLength(3);
    const lines = qa(el, "groups-rail-activity").map((x) => x.textContent?.trim());
    expect(lines[0]).toMatch(/^Last active /);
    expect(lines[1]).toBe("No posts yet");

    const search = q(el, "groups-rail-search") as HTMLInputElement;
    search.value = "dog";
    search.dispatchEvent(new Event("input"));
    await flush();
    expect(qa(el, "groups-rail-item").map((x) => x.textContent)).toEqual([expect.stringContaining("Group dogs")]);
    search.value = "zzz";
    search.dispatchEvent(new Event("input"));
    await flush();
    expect(el.textContent).toContain("No matching groups.");
  });
});
