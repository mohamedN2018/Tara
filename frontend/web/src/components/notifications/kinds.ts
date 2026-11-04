// How each notification kind looks and what can be done from it. The server's
// kind registry (services/notification/notifications/registry.py) owns the
// category, channels, grouping and the deep link (`notification.url`); this
// file only owns presentation.
import {
  AtSign,
  Bell,
  CalendarDays,
  Flag,
  Heart,
  type LucideIcon,
  Megaphone,
  MessageCircle,
  MessageSquare,
  Phone,
  PhoneMissed,
  Share2,
  ShoppingBag,
  Tag,
  UserCheck,
  UserPlus,
  UsersRound,
  Video,
} from "lucide-vue-next";

import { sameOriginPath } from "@/lib/redirect";
import type { Notification } from "@/types";

const KIND_ICONS: Record<string, LucideIcon> = {
  "post.reaction": Heart,
  "post.comment": MessageSquare,
  "comment.reply": MessageSquare,
  "post.share": Share2,
  mention: AtSign,
  "post.tag": Tag,
  "friend.request": UserPlus,
  "friend.accepted": UserCheck,
  follow: UserPlus,
  message: MessageCircle,
  call: Phone,
  "call.missed": PhoneMissed,
  "listing.status": ShoppingBag,
  "listing.inquiry": ShoppingBag,
  "page.follow": Flag,
  "ad.review": Megaphone,
  "gathering.invite": CalendarDays,
  "gathering.reminder": CalendarDays,
  "gathering.update": CalendarDays,
  "gathering.cancel": CalendarDays,
  "gathering.rsvp": CalendarDays,
  "group.invite": UsersRound,
  "group.request": UsersRound,
  "group.approved": UsersRound,
  "group.post": UsersRound,
  "group.role": UsersRound,
  "group.announcement": Megaphone,
  "video.ready": Video,
};

export const iconFor = (kind: string): LucideIcon => KIND_ICONS[kind] ?? Bell;

/** Translation key segment for a kind ("post.reaction" -> "post_reaction"). */
export const kindKey = (kind: string) => kind.replace(/\./g, "_");

// The order categories and kinds appear in Settings and the filter chips.
export const CATEGORY_ORDER = ["social", "connections", "messages", "groups", "marketplace", "pages", "ads"];

export type InlineAction = "accept" | "decline" | "follow_back";

/** Buttons shown on the row itself. Resolved rows show their outcome instead. */
export function inlineActions(n: Notification): InlineAction[] {
  if (n.resolution) return [];
  if (n.kind === "friend.request" && n.data?.request_id) return ["accept", "decline"];
  if (n.kind === "follow" && (n.actor_count ?? 1) <= 1 && n.actor_id) return ["follow_back"];
  return [];
}

/** Others besides the named actor, for "X and 3 others ...". */
export const othersCount = (n: Notification) => Math.max(0, (n.actor_count ?? 1) - 1);

type Translate = (key: string, named?: Record<string, unknown>, plural?: number) => string;

/**
 * The row's sentence. The stored `body` is a fixed English sentence (or a message
 * preview), so text is rebuilt from the kind; an unknown kind shows the body.
 */
export function notificationText(
  n: Notification,
  t: Translate,
  te: (key: string) => boolean,
  name: string,
): string {
  const segment = kindKey(n.kind);
  const key = `notifications.kinds.${segment}`;
  if (!te(key)) return n.body;
  if (n.kind === "listing.status") {
    const status = String(n.data?.status ?? n.body.split(" ").pop() ?? "");
    const statusKey = `market.statuses.${status}`;
    return t(key, { status: te(statusKey) ? t(statusKey) : status });
  }
  if (n.kind === "call.missed" && n.data?.call_kind === "video") {
    return t("notifications.kinds.call_missed_video", { name });
  }
  if (n.kind === "group.role") {
    const role = String(n.data?.role ?? "");
    const roleKey = `groups.roles.${role}`;
    return t(key, { name, role: te(roleKey) ? t(roleKey) : role });
  }
  if (n.kind === "gathering.reminder" && n.data?.window === "1h") {
    return t("notifications.kinds.gathering_reminder_hour");
  }
  const others = othersCount(n);
  if (n.kind === "gathering.rsvp" && others === 0 && n.data?.status === "interested") {
    return t("notifications.kinds.gathering_rsvp_interested", { name });
  }
  if (n.kind === "message" && others === 0) {
    // One sender, several messages (`message_count`); or a preview that is blank:
    // an attachment, or a message edited or deleted since.
    const count = Number(n.data?.message_count ?? 1);
    if (Number.isInteger(count) && count > 1) return t("notifications.kinds.message_many", { name, count }, count);
    if (!n.body) return t("notifications.kinds.message_blank", { name });
  }
  const grouped = `notifications.grouped.${segment}`;
  if (others > 0 && te(grouped)) return t(grouped, { name, count: others }, others);
  return t(key, { name, body: n.body });
}

/**
 * Add the thread root to a reply's comment link (`?thread=`), so the post page
 * can open that thread directly instead of searching for the reply.
 */
function withThread(path: string, n: Notification): string {
  const root = n.data?.parent_id;
  if (n.kind !== "comment.reply" || typeof root !== "string" || !root) return path;
  const [base, query = ""] = path.split("?", 2);
  const params = new URLSearchParams(query);
  if (!params.has("comment") || params.has("thread")) return path;
  params.set("thread", root);
  return `${base}?${params}`;
}

/** The row's link: the server's `url` when it is same-origin, else built from the subject. */
export function urlFor(n: Notification): string {
  const own = sameOriginPath(n.url);
  if (own) return withThread(own, n);
  const [type, id] = (n.subject_ref || "").split(":");
  if (type === "post" && id) return `/posts/${id}`;
  if (type === "conversation" && id) return `/messages/${id}`;
  if (type === "listing" && id) return `/marketplace/${id}`;
  if (type === "gathering" && id) return `/events/${id}`;
  if (type === "group" && id) {
    const handle = n.data?.group_handle;
    return `/groups/${encodeURIComponent(typeof handle === "string" && handle ? handle : id)}`;
  }
  if (n.actor_id) return `/u/id/${n.actor_id}`;
  return "/notifications";
}
