import { afterEach, describe, expect, it, vi } from "vitest";

import { CATEGORY_ORDER, iconFor, notificationText, urlFor } from "@/components/notifications/kinds";
import { navItems } from "@/components/layout/navItems";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import {
  assignableRoles,
  canActOn,
  type Group,
  type GroupCan,
  groupChanges,
  GROUP_ERRORS,
  groupPath,
  groupPostsService,
  groupsService,
  joinState,
  manageSections,
  myGroupsFeed,
  suggestHandle,
  validateHandle,
} from "@/services/groups";
import { postService } from "@/services/post";
import type { Notification, Post } from "@/types";

const g = i18n.global;
const EMPTY_PAGE = { data: [], page: { next_cursor: null, prev_cursor: null, has_more: false } };

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

function group(over: Partial<Group> = {}): Group {
  return {
    id: "g1",
    handle: "readers",
    name: "Readers",
    description: "",
    category: "general",
    privacy: "private",
    membership_approval: true,
    post_approval: false,
    cover_media_id: null,
    member_count: 3,
    created_at: "2026-11-01T10:00:00Z",
    updated_at: "2026-11-01T10:00:00Z",
    content_visible: false,
    viewer: { role: null, state: null, notify_posts: false, can: { ...NO_CAN } },
    ...over,
  };
}

function row(over: Partial<Notification> = {}): Notification {
  return {
    id: "n1",
    kind: "group.invite",
    actor_id: "a1",
    actor_count: 1,
    subject_ref: "group:g1",
    body: "",
    read_at: null,
    created_at: "2026-11-01T10:00:00Z",
    last_event_at: "2026-11-01T10:00:00Z",
    url: "",
    ...over,
  };
}

afterEach(() => {
  g.locale.value = "en";
  vi.restoreAllMocks();
});

describe("group handles", () => {
  it.each([
    ["ab", "too_short"],
    ["a".repeat(31), "too_long"],
    ["Readers", "invalid_chars"],
    ["book-club", "invalid_chars"],
    ["قراء", "invalid_chars"],
    ["new", "reserved"],
    ["manage", "reserved"],
    ["book_club_2026", null],
  ])("validates %s", (handle, problem) => {
    expect(validateHandle(handle)).toBe(problem);
  });

  it("suggests a handle from a Latin name and leaves Arabic names to the person", () => {
    expect(suggestHandle("Café Lovers - Cairo")).toBe("cafe_lovers_cairo");
    expect(suggestHandle("نادي القراءة")).toBe("");
    expect(suggestHandle("x".repeat(40))).toHaveLength(30);
  });
});

describe("join button", () => {
  it.each([
    [{ state: null, approval: false }, "join"],
    [{ state: null, approval: true }, "request"],
    [{ state: "requested", approval: true }, "requested"],
    [{ state: "invited", approval: true }, "invited"],
    [{ state: "active", approval: true }, "joined"],
  ] as const)("shows %o as %s", ({ state, approval }, expected) => {
    const gr = group({ membership_approval: approval });
    gr.viewer.state = state;
    expect(joinState(gr)).toBe(expected);
  });
});

describe("permissions in the dashboard", () => {
  it("shows nothing to a member", () => {
    expect(manageSections(NO_CAN)).toEqual([]);
    expect(manageSections(null)).toEqual([]);
  });

  it("gives a moderator the queues but not settings or rules", () => {
    const can = { ...NO_CAN, approve_requests: true, approve_posts: true, moderate: true, pin: true, view_reports: true };
    expect(manageSections(can)).toEqual(["requests", "posts", "members", "banned", "reports"]);
  });

  it("gives an admin every section in order", () => {
    const all = Object.fromEntries(Object.keys(NO_CAN).map((k) => [k, true])) as unknown as GroupCan;
    expect(manageSections(all)).toEqual(["requests", "posts", "members", "banned", "rules", "settings", "reports"]);
  });

  it("only offers roles below the actor's own (owners may name owners)", () => {
    expect(assignableRoles("owner", "admin")).toEqual(["owner", "admin", "moderator", "member"]);
    expect(assignableRoles("admin", "member")).toEqual(["moderator", "member"]);
    expect(assignableRoles("admin", "admin")).toEqual([]);
    expect(assignableRoles("moderator", "member")).toEqual(["member"]);
    expect(assignableRoles(null, "member")).toEqual([]);
  });

  it("lets staff act only on lower ranks", () => {
    expect(canActOn("moderator", "member")).toBe(true);
    expect(canActOn("moderator", "moderator")).toBe(false);
    expect(canActOn("admin", "owner")).toBe(false);
    expect(canActOn("owner", "owner")).toBe(true);
    expect(canActOn("member", "member")).toBe(false);
  });

  it("sends only changed settings", () => {
    const gr = group({ privacy: "public", name: "Readers" });
    expect(
      groupChanges(
        {
          name: " Readers 2 ",
          description: "",
          category: "general",
          privacy: "hidden",
          membership_approval: true,
          post_approval: false,
          cover_media_id: null,
        },
        gr,
      ),
    ).toEqual({ name: "Readers 2", privacy: "hidden" });
  });
});

describe("groups service", () => {
  it("lists a scope with its filters and cursor", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: EMPTY_PAGE });
    await groupsService.list("discover", "c1", "books", "education");
    expect(get).toHaveBeenCalledWith("/groups/", {
      params: { scope: "discover", cursor: "c1", q: "books", category: "education" },
    });
    await groupsService.list();
    expect(get).toHaveBeenLastCalledWith("/groups/", { params: { scope: "mine" } });
  });

  it("uses the handle or id in member and moderation paths", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: { invited: ["f1"] } } });
    expect(await groupsService.invite("readers", ["f1"])).toEqual(["f1"]);
    expect(post).toHaveBeenCalledWith("/groups/readers/invite/", { account_ids: ["f1"] });
    await groupsService.approveRequest("readers", "u1");
    expect(post).toHaveBeenLastCalledWith("/groups/readers/requests/u1/approve/");
    await groupsService.ban("readers", "u1");
    expect(post).toHaveBeenLastCalledWith("/groups/readers/members/u1/ban/");
    await groupsService.report("readers", "spam");
    expect(post).toHaveBeenLastCalledWith("/groups/readers/report/", { reason: "spam" });
    const patch = vi.spyOn(api, "patch").mockResolvedValue({ data: { data: {} } });
    await groupsService.setRole("readers", "u1", "moderator");
    expect(patch).toHaveBeenCalledWith("/groups/readers/members/u1/", { role: "moderator" });
    const put = vi.spyOn(api, "put").mockResolvedValue({ data: { data: [] } });
    await groupsService.reorderRules("readers", ["r2", "r1"]);
    expect(put).toHaveBeenCalledWith("/groups/readers/rules/order/", { ids: ["r2", "r1"] });
  });

  it("asks the post service for a group's feed views", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: EMPTY_PAGE });
    await groupPostsService.feed("g1");
    expect(get).toHaveBeenCalledWith("/posts/groups/g1/", { params: {} });
    await groupPostsService.feed("g1", "pending", "c2");
    expect(get).toHaveBeenLastCalledWith("/posts/groups/g1/", { params: { view: "pending", cursor: "c2" } });
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: {} } });
    await groupPostsService.pin("p1");
    expect(post).toHaveBeenCalledWith("/posts/p1/pin/");
    await groupPostsService.dismissReport("g1", "comment", "c1");
    expect(post).toHaveBeenLastCalledWith("/posts/groups/g1/reports/dismiss/", { target_type: "comment", target_id: "c1" });
  });

  it("posts into a group with its id", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: {} } });
    await postService.create({ body: "hello", group_id: "g1" });
    expect(post).toHaveBeenCalledWith("/posts/", expect.objectContaining({ body: "hello", group_id: "g1" }));
  });

  it("merges my groups' first pages newest first and skips a group that fails", async () => {
    const p = (id: string, at: string) => ({ id, created_at: at }) as Post;
    vi.spyOn(groupPostsService, "feed").mockImplementation(async (id: string) => {
      if (id === "bad") throw new Error("boom");
      return {
        data: id === "a" ? [p("a1", "2026-11-01T10:00:00Z")] : [p("b1", "2026-11-02T10:00:00Z")],
        page: EMPTY_PAGE.page,
      };
    });
    const merged = await myGroupsFeed([group({ id: "a" }), group({ id: "b" }), group({ id: "bad" })]);
    expect(merged.map((x) => x.post.id)).toEqual(["b1", "a1"]);
  });

  it("links hidden groups by id", () => {
    expect(groupPath({ handle: "readers", id: "g1" })).toBe("/groups/readers");
    expect(groupPath({ handle: "", id: "g1" })).toBe("/groups/g1");
  });

  it("explains the last-owner rule in both languages", () => {
    const err = { response: { status: 409, data: { error: { code: "last_owner", message: "x" } } } };
    expect(errorMessage(err, GROUP_ERRORS)).toContain("at least one owner");
    g.locale.value = "ar";
    expect(errorMessage(err, GROUP_ERRORS)).toContain("مالك واحد على الأقل");
  });
});

describe("group words and navigation", () => {
  it("has Groups in the sidebar", () => {
    expect(navItems.find((i) => i.route === "/groups")?.labelKey).toBe("nav.groups");
    expect(g.t("nav.groups")).toBe("Groups");
  });

  it("pluralises member counts in Arabic and English", () => {
    expect(g.t("groups.memberCount", { count: 1 }, 1)).toBe("1 member");
    expect(g.t("groups.memberCount", { count: 7 }, 7)).toBe("7 members");
    g.locale.value = "ar";
    expect(g.t("groups.memberCount", { count: 1 }, 1)).toBe("عضو واحد");
    expect(g.t("groups.memberCount", { count: 2 }, 2)).toBe("عضوان");
    expect(g.t("groups.memberCount", { count: 5 }, 5)).toBe("5 أعضاء");
    expect(g.t("groups.memberCount", { count: 12 }, 12)).toBe("12 عضوًا");
    expect(g.t("groups.memberCount", { count: 100 }, 100)).toBe("100 عضو");
  });
});

describe("group notifications", () => {
  it("links to the group by handle, or by id without one", () => {
    expect(urlFor(row({ data: { group_handle: "readers" } }))).toBe("/groups/readers");
    expect(urlFor(row())).toBe("/groups/g1");
    expect(urlFor(row({ url: "/groups/readers" }))).toBe("/groups/readers");
  });

  it("words each kind, with the role translated", () => {
    const text = (n: Notification) => notificationText(n, g.t as never, g.te, "Sara");
    expect(text(row())).toBe("Sara invited you to join a group");
    expect(text(row({ kind: "group.role", data: { role: "moderator" } }))).toBe("Sara made you Moderator in a group");
    expect(text(row({ kind: "group.request", actor_count: 3 }))).toBe("Sara and 2 others asked to join your group");
    g.locale.value = "ar";
    expect(text(row({ kind: "group.role", data: { role: "admin" } }))).toBe("جعلك Sara بدور مشرف في مجموعة");
    expect(text(row({ kind: "group.request", actor_count: 2 }))).toBe("طلب Sara وشخص آخر الانضمام إلى مجموعتك");
  });

  it("has a groups category and icons for every kind", () => {
    expect(CATEGORY_ORDER).toContain("groups");
    for (const kind of ["group.invite", "group.request", "group.approved", "group.post", "group.role", "group.announcement"]) {
      expect(iconFor(kind)).not.toBe(iconFor("no.such.kind"));
      expect(g.te(`notifications.kinds.${kind.replace(".", "_")}`)).toBe(true);
      expect(g.te(`settings.notif.${kind.replace(".", "_")}`)).toBe(true);
    }
    expect(g.t("notifications.categories.groups")).toBe("Groups");
  });
});
