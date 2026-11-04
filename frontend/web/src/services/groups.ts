import { api } from "@/lib/api";
import type { CursorPage, Post } from "@/types";

// Groups (profile's `groups` app, roadmap 1.11) and group posts (post service).
// The server owns every rule: visibility (a hidden group is a 404), the role
// hierarchy, last-owner protection, join and post approval. `viewer.can` is
// computed there; the SPA only uses it to decide what to show.

export type GroupPrivacy = "public" | "private" | "hidden";
export type GroupRole = "owner" | "admin" | "moderator" | "member";
export type MemberState = "requested" | "invited" | "active" | "banned";
export type GroupScope = "mine" | "discover" | "invited" | "requested" | "managed";
export type GroupFeedView = "discussion" | "featured" | "pending" | "media";
export type GroupCategory =
  | "general"
  | "education"
  | "business"
  | "technology"
  | "sports"
  | "gaming"
  | "arts"
  | "entertainment"
  | "health"
  | "travel"
  | "food"
  | "parenting"
  | "religion"
  | "local"
  | "buy_sell"
  | "hobbies"
  | "science"
  | "other";
export type GroupReportReason =
  | "spam"
  | "scam"
  | "hate"
  | "violence"
  | "nudity"
  | "harassment"
  | "false_information"
  | "other";

export const GROUP_PRIVACIES: GroupPrivacy[] = ["public", "private", "hidden"];
export const GROUP_ROLES: GroupRole[] = ["owner", "admin", "moderator", "member"];
export const GROUP_CATEGORIES: GroupCategory[] = [
  "general",
  "education",
  "business",
  "technology",
  "sports",
  "gaming",
  "arts",
  "entertainment",
  "health",
  "travel",
  "food",
  "parenting",
  "religion",
  "local",
  "buy_sell",
  "hobbies",
  "science",
  "other",
];
export const GROUP_REPORT_REASONS: GroupReportReason[] = [
  "spam",
  "scam",
  "hate",
  "violence",
  "nudity",
  "harassment",
  "false_information",
  "other",
];
export const MAX_NAME = 100;
export const MAX_DESCRIPTION = 5000;
export const MAX_RULES = 10;
export const MAX_RULE_TITLE = 100;
export const MAX_RULE_BODY = 500;
export const MAX_INVITES = 50;
export const HANDLE_MIN = 3;
export const HANDLE_MAX = 30;
export const RESERVED_HANDLES = new Set([
  "new",
  "discover",
  "mine",
  "id",
  "manage",
  "admin",
  "tara",
  "feed",
  "invites",
  "suggestions",
  "lookup",
]);

const RANK: Record<GroupRole, number> = { owner: 4, admin: 3, moderator: 2, member: 1 };

export interface GroupCan {
  post: boolean;
  invite: boolean;
  edit: boolean;
  delete: boolean;
  change_privacy: boolean;
  manage_rules: boolean;
  approve_requests: boolean;
  approve_posts: boolean;
  moderate: boolean;
  change_roles: boolean;
  pin: boolean;
  view_reports: boolean;
}

export interface GroupViewer {
  role: GroupRole | null;
  state: MemberState | null;
  notify_posts: boolean;
  can: GroupCan;
}

export interface GroupRule {
  id: string;
  title: string;
  body: string;
  position: number;
}

export interface Group {
  id: string;
  handle: string;
  name: string;
  description: string;
  category: GroupCategory;
  privacy: GroupPrivacy;
  membership_approval: boolean;
  post_approval: boolean;
  cover_media_id: string | null;
  member_count: number;
  created_at: string;
  updated_at: string;
  content_visible: boolean;
  rules?: GroupRule[];
  viewer: GroupViewer;
  /** Suggestions only. */
  friend_member_count?: number;
  friend_ids?: string[];
}

export interface Membership {
  account_id: string;
  role: GroupRole;
  state: MemberState;
  notify_posts: boolean;
  invited_by: string | null;
  joined_at: string | null;
  created_at: string;
}

export interface GroupInput {
  name: string;
  handle: string;
  description: string;
  category: GroupCategory;
  privacy: GroupPrivacy;
  membership_approval: boolean;
  post_approval: boolean;
  cover_media_id?: string | null;
  rules?: { title: string; body: string }[];
}

export type GroupChanges = Partial<Omit<GroupInput, "handle" | "rules">>;

/** The fields the creation form and the settings section share. */
export interface GroupFormValue {
  name: string;
  description: string;
  category: GroupCategory;
  privacy: GroupPrivacy;
  membership_approval: boolean;
  post_approval: boolean;
  cover_media_id: string | null;
}

/** Only the fields that differ from the group, for a PATCH. */
export function groupChanges(value: GroupFormValue, group: Group): GroupChanges {
  const out: GroupChanges = {};
  for (const key of Object.keys(value) as (keyof GroupFormValue)[]) {
    if (value[key] !== group[key]) (out as Record<string, unknown>)[key] = value[key];
  }
  if (typeof out.name === "string") out.name = out.name.trim();
  return out;
}

export interface GroupReportItem {
  target_type: "post" | "comment";
  target_id: string;
  post_id: string;
  author_id: string;
  excerpt: string;
  report_count: number;
  reasons: string[];
  last_reported_at: string;
}

/** Group error codes with their own message (`groups.errors.<code>`). */
export const GROUP_ERRORS: Record<string, string> = Object.fromEntries(
  [
    "handle_taken",
    "last_owner",
    "role_not_allowed",
    "invite_not_friend",
    "not_group_member",
    "too_many_rules",
    "media_already_attached",
    "conflict",
  ].map((code) => [code, `groups.errors.${code}`]),
);

// ---- pure helpers (unit-tested) ---------------------------------------------------

export type HandleProblem = "too_short" | "too_long" | "invalid_chars" | "reserved";

/** The same rule the server applies; null when the handle can be tried. */
export function validateHandle(handle: string): HandleProblem | null {
  if (handle.length < HANDLE_MIN) return "too_short";
  if (handle.length > HANDLE_MAX) return "too_long";
  if (!/^[a-z0-9_]+$/.test(handle)) return "invalid_chars";
  if (RESERVED_HANDLES.has(handle)) return "reserved";
  return null;
}

/** A handle suggested from the name: Latin letters, digits and underscores only. */
export function suggestHandle(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[\s-]+/g, "_")
    .replace(/[^a-z0-9_]/g, "")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "")
    .slice(0, HANDLE_MAX);
}

export type JoinState = "join" | "request" | "requested" | "invited" | "joined";

/** What the join button shows for the viewer. */
export function joinState(group: Pick<Group, "membership_approval" | "viewer">): JoinState {
  const state = group.viewer?.state;
  if (state === "active") return "joined";
  if (state === "requested") return "requested";
  if (state === "invited") return "invited";
  return group.membership_approval ? "request" : "join";
}

export function isStaff(role: GroupRole | null | undefined): boolean {
  return role === "owner" || role === "admin" || role === "moderator";
}

export type ManageSection = "requests" | "invited" | "posts" | "members" | "banned" | "rules" | "settings" | "reports";

/** The dashboard sections the viewer may open, in display order. */
export function manageSections(can: Partial<GroupCan> | null | undefined): ManageSection[] {
  if (!can) return [];
  const out: ManageSection[] = [];
  if (can.approve_requests) out.push("requests", "invited");
  if (can.approve_posts) out.push("posts");
  if (can.moderate || can.change_roles) out.push("members");
  if (can.moderate) out.push("banned");
  if (can.manage_rules) out.push("rules");
  if (can.edit) out.push("settings");
  if (can.view_reports) out.push("reports");
  return out;
}

/** Roles the actor may give a member (the server checks again). Owners may name owners. */
export function assignableRoles(actor: GroupRole | null | undefined, target: GroupRole): GroupRole[] {
  if (!actor) return [];
  if (actor === "owner") return [...GROUP_ROLES];
  if (RANK[actor] <= RANK[target]) return [];
  return GROUP_ROLES.filter((r) => RANK[r] < RANK[actor]);
}

/** Whether the actor outranks the target (remove, ban). Owners act on owners too. */
export function canActOn(actor: GroupRole | null | undefined, target: GroupRole): boolean {
  if (!actor || !isStaff(actor)) return false;
  if (actor === "owner") return true;
  return RANK[actor] > RANK[target];
}

/** The path segment for a group: its handle, or its id (hidden groups' links carry ids). */
export const groupPath = (group: Pick<Group, "handle" | "id">) => `/groups/${group.handle || group.id}`;

// ---- profile endpoints -------------------------------------------------------------

const ref = (r: string) => encodeURIComponent(r);

export const groupsService = {
  async list(
    scope: GroupScope = "mine",
    cursor?: string | null,
    q = "",
    category = "",
  ): Promise<CursorPage<Group>> {
    const { data } = await api.get<CursorPage<Group>>("/groups/", {
      params: { scope, ...(cursor ? { cursor } : {}), ...(q ? { q } : {}), ...(category ? { category } : {}) },
    });
    return data;
  },

  async suggestions(): Promise<Group[]> {
    const { data } = await api.get<{ data: Group[] }>("/groups/suggestions/");
    return data.data;
  },

  async dismissSuggestion(groupId: string): Promise<void> {
    await api.post(`/groups/suggestions/${ref(groupId)}/dismiss/`);
  },

  async create(input: GroupInput): Promise<Group> {
    const { data } = await api.post<{ data: Group }>("/groups/", input);
    return data.data;
  },

  async get(groupRef: string): Promise<Group> {
    const { data } = await api.get<{ data: Group }>(`/groups/${ref(groupRef)}/`);
    return data.data;
  },

  async update(groupRef: string, changes: GroupChanges): Promise<Group> {
    const { data } = await api.patch<{ data: Group }>(`/groups/${ref(groupRef)}/`, changes);
    return data.data;
  },

  async remove(groupRef: string): Promise<void> {
    await api.delete(`/groups/${ref(groupRef)}/`);
  },

  async join(groupRef: string): Promise<Membership> {
    const { data } = await api.post<{ data: Membership }>(`/groups/${ref(groupRef)}/join/`);
    return data.data;
  },

  /** Cancel my request, or decline my invitation. */
  async cancelJoin(groupRef: string): Promise<void> {
    await api.delete(`/groups/${ref(groupRef)}/join/`);
  },

  async leave(groupRef: string): Promise<void> {
    await api.post(`/groups/${ref(groupRef)}/leave/`);
  },

  async setNotifyPosts(groupRef: string, notifyPosts: boolean): Promise<Membership> {
    const { data } = await api.patch<{ data: Membership }>(`/groups/${ref(groupRef)}/membership/`, {
      notify_posts: notifyPosts,
    });
    return data.data;
  },

  async invite(groupRef: string, accountIds: string[]): Promise<string[]> {
    const { data } = await api.post<{ data: { invited: string[] } }>(`/groups/${ref(groupRef)}/invite/`, {
      account_ids: accountIds,
    });
    return data.data.invited;
  },

  async members(
    groupRef: string,
    opts: { state?: MemberState; role?: GroupRole | ""; q?: string; cursor?: string | null } = {},
  ): Promise<CursorPage<Membership>> {
    const { data } = await api.get<CursorPage<Membership>>(`/groups/${ref(groupRef)}/members/`, {
      params: {
        state: opts.state ?? "active",
        ...(opts.role ? { role: opts.role } : {}),
        ...(opts.q ? { q: opts.q } : {}),
        ...(opts.cursor ? { cursor: opts.cursor } : {}),
      },
    });
    return data;
  },

  async approveRequest(groupRef: string, accountId: string): Promise<Membership> {
    const { data } = await api.post<{ data: Membership }>(
      `/groups/${ref(groupRef)}/requests/${ref(accountId)}/approve/`,
    );
    return data.data;
  },

  async declineRequest(groupRef: string, accountId: string): Promise<void> {
    await api.post(`/groups/${ref(groupRef)}/requests/${ref(accountId)}/decline/`);
  },

  /** Withdraw a pending invitation (staff who may approve requests). */
  async revokeInvite(groupRef: string, accountId: string): Promise<void> {
    await api.post(`/groups/${ref(groupRef)}/invites/${ref(accountId)}/revoke/`);
  },

  async removeMember(groupRef: string, accountId: string): Promise<void> {
    await api.post(`/groups/${ref(groupRef)}/members/${ref(accountId)}/remove/`);
  },

  async ban(groupRef: string, accountId: string): Promise<Membership> {
    const { data } = await api.post<{ data: Membership }>(`/groups/${ref(groupRef)}/members/${ref(accountId)}/ban/`);
    return data.data;
  },

  async unban(groupRef: string, accountId: string): Promise<void> {
    await api.post(`/groups/${ref(groupRef)}/members/${ref(accountId)}/unban/`);
  },

  async setRole(groupRef: string, accountId: string, role: GroupRole): Promise<Membership> {
    const { data } = await api.patch<{ data: Membership }>(`/groups/${ref(groupRef)}/members/${ref(accountId)}/`, {
      role,
    });
    return data.data;
  },

  async rules(groupRef: string): Promise<GroupRule[]> {
    const { data } = await api.get<{ data: GroupRule[] }>(`/groups/${ref(groupRef)}/rules/`);
    return data.data;
  },

  async addRule(groupRef: string, rule: { title: string; body: string }): Promise<GroupRule> {
    const { data } = await api.post<{ data: GroupRule }>(`/groups/${ref(groupRef)}/rules/`, rule);
    return data.data;
  },

  async updateRule(groupRef: string, id: string, rule: { title?: string; body?: string }): Promise<GroupRule> {
    const { data } = await api.patch<{ data: GroupRule }>(`/groups/${ref(groupRef)}/rules/${ref(id)}/`, rule);
    return data.data;
  },

  async deleteRule(groupRef: string, id: string): Promise<void> {
    await api.delete(`/groups/${ref(groupRef)}/rules/${ref(id)}/`);
  },

  async reorderRules(groupRef: string, ids: string[]): Promise<GroupRule[]> {
    const { data } = await api.put<{ data: GroupRule[] }>(`/groups/${ref(groupRef)}/rules/order/`, { ids });
    return data.data;
  },

  async report(groupRef: string, reason: GroupReportReason): Promise<void> {
    await api.post(`/groups/${ref(groupRef)}/report/`, { reason });
  },
};

// ---- post-service endpoints for groups ---------------------------------------------

export const groupPostsService = {
  async feed(groupId: string, view: GroupFeedView = "discussion", cursor?: string | null): Promise<CursorPage<Post>> {
    const { data } = await api.get<CursorPage<Post>>(`/posts/groups/${ref(groupId)}/`, {
      params: { ...(view !== "discussion" ? { view } : {}), ...(cursor ? { cursor } : {}) },
    });
    return data;
  },

  async approve(postId: string): Promise<Post> {
    const { data } = await api.post<{ data: Post }>(`/posts/${ref(postId)}/approve/`);
    return data.data;
  },

  async decline(postId: string): Promise<void> {
    await api.post(`/posts/${ref(postId)}/decline/`);
  },

  async pin(postId: string): Promise<void> {
    await api.post(`/posts/${ref(postId)}/pin/`);
  },

  async unpin(postId: string): Promise<void> {
    await api.delete(`/posts/${ref(postId)}/pin/`);
  },

  async reports(groupId: string, cursor?: string | null): Promise<CursorPage<GroupReportItem>> {
    const { data } = await api.get<CursorPage<GroupReportItem>>(`/posts/groups/${ref(groupId)}/reports/`, {
      params: cursor ? { cursor } : {},
    });
    return data;
  },

  async dismissReport(groupId: string, targetType: "post" | "comment", targetId: string): Promise<void> {
    await api.post(`/posts/groups/${ref(groupId)}/reports/dismiss/`, { target_type: targetType, target_id: targetId });
  },
};

/**
 * The newest posts across the viewer's groups: the first page of each group's
 * discussion, merged newest first. A group that fails is left out.
 */
export async function myGroupsFeed(groups: Group[], perGroup = 5): Promise<{ post: Post; group: Group }[]> {
  const pages = await Promise.all(
    groups.map(async (group) => {
      try {
        const page = await groupPostsService.feed(group.id);
        return page.data.slice(0, perGroup).map((post) => ({ post, group }));
      } catch {
        return [];
      }
    }),
  );
  return pages
    .flat()
    .sort((x, y) => new Date(y.post.created_at).getTime() - new Date(x.post.created_at).getTime());
}
