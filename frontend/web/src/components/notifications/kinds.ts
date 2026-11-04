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
  Scale,
  Share2,
  ShieldAlert,
  ShoppingBag,
  Tag,
  UserCheck,
  UserPlus,
  UsersRound,
  Video,
} from "lucide-vue-next";

import { withoutAppLinks } from "@/lib/chat";
import { sameOriginPath } from "@/lib/redirect";
import type { Notification } from "@/types";

const KIND_ICONS: Record<string, LucideIcon> = {
  "post.reaction": Heart,
  "story.reaction": Heart,
  "post.comment": MessageSquare,
  "comment.reply": MessageSquare,
  "post.share": Share2,
  mention: AtSign,
  "post.tag": Tag,
  "friend.request": UserPlus,
  "friend.accepted": UserCheck,
  follow: UserPlus,
  message: MessageCircle,
  "message.page": MessageCircle,
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
  // Account status and notices (T7): open the Support inbox.
  "moderation.decision": ShieldAlert,
  "moderation.appeal": Scale,
  "system.notice": Megaphone,
};

export const iconFor = (kind: string): LucideIcon => KIND_ICONS[kind] ?? Bell;

/** Translation key segment for a kind ("post.reaction" -> "post_reaction"). */
export const kindKey = (kind: string) => kind.replace(/\./g, "_");

// The order categories and kinds appear in Settings and the filter chips.
export const CATEGORY_ORDER = ["social", "connections", "messages", "groups", "marketplace", "pages", "ads", "account"];

// The page's filter chips: every category, plus account notices (moderation decisions, appeals).
export const FILTER_CATEGORIES = [...new Set([...CATEGORY_ORDER, "account"])];

export type InlineAction = "accept" | "decline" | "follow_back" | "join" | "decline_invite";

/** Buttons shown on the row itself. Resolved rows show their outcome instead. */
export function inlineActions(n: Notification): InlineAction[] {
  if (n.resolution) return [];
  if (n.kind === "friend.request" && n.data?.request_id) return ["accept", "decline"];
  if (n.kind === "follow" && (n.actor_count ?? 1) <= 1 && n.actor_id) return ["follow_back"];
  // A group invitation: join or decline right here (groups service, then the outcome is stored).
  if (n.kind === "group.invite" && (n.data?.group_id || n.data?.group_handle)) return ["join", "decline_invite"];
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
  // Account status (T7): fixed sentences from the Tara team; a notice is the staff's own text.
  if (n.kind === "system.notice") return n.body;
  if (n.kind === "moderation.decision" || n.kind === "moderation.appeal") {
    const what = String(n.kind === "moderation.decision" ? n.data?.decision : n.data?.status);
    const type = String(n.data?.target_type ?? "");
    const target = te(`safety.targets.${type}`) ? t(`safety.targets.${type}`) : t("safety.notify.target");
    const sentence = `safety.notify.${n.kind === "moderation.decision" ? "decision" : "appeal"}_${what}`;
    return te(sentence) ? t(sentence, { target }) : n.body;
  }
  if (n.kind === "message.page") {
    // A message to a Page the viewer helps run: "<name> to <Page>: <text>".
    const page = String(n.data?.page_name || t("chatTeam.pageFallback"));
    const body = withoutAppLinks(n.body ?? "");
    const count = Number(n.data?.message_count ?? 1);
    if (Number.isInteger(count) && count > 1) return t("chatTeam.notify.many", { name, page, count }, count);
    return body ? t("chatTeam.notify.message", { name, page, body }) : t("chatTeam.notify.blank", { name, page });
  }
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
    if (!withoutAppLinks(n.body ?? "")) return t("notifications.kinds.message_blank", { name });
    return t(key, { name, body: withoutAppLinks(n.body) });
  }
  const grouped = `notifications.grouped.${segment}`;
  if (others > 0 && te(grouped)) return t(grouped, { name, count: others }, others);
  return t(key, { name, body: n.body });
}

/**
 * The message text a row's sentence quotes ("Mona: see you at 5"), or "" when
 * it quotes none. The row isolates it, so a message in the other script keeps
 * its own direction and punctuation ("seen?" never shows as "?seen").
 */
export function notificationExcerpt(n: Notification): string {
  if (n.kind !== "message" && n.kind !== "message.page") return "";
  if (n.kind === "message" && othersCount(n) > 0) return "";
  const count = Number(n.data?.message_count ?? 1);
  if (Number.isInteger(count) && count > 1) return "";
  return withoutAppLinks(n.body ?? "");
}

export type TextPart = { text: string; isolate?: "name" | "excerpt" };

/**
 * Split a sentence into plain text and the parts to isolate: the actor's name
 * (first occurrence) and the quoted excerpt (last occurrence, outside the name).
 */
export function isolateParts(text: string, name: string, excerpt: string): TextPart[] {
  const ranges: { start: number; end: number; isolate: "name" | "excerpt" }[] = [];
  const at = name ? text.indexOf(name) : -1;
  if (at >= 0) ranges.push({ start: at, end: at + name.length, isolate: "name" });
  if (excerpt) {
    let from = text.lastIndexOf(excerpt);
    while (from >= 0 && at >= 0 && from < at + name.length && from + excerpt.length > at) {
      from = from > 0 ? text.lastIndexOf(excerpt, from - 1) : -1;
    }
    if (from >= 0) ranges.push({ start: from, end: from + excerpt.length, isolate: "excerpt" });
  }
  ranges.sort((a, b) => a.start - b.start);
  const parts: TextPart[] = [];
  let pos = 0;
  for (const r of ranges) {
    if (r.start > pos) parts.push({ text: text.slice(pos, r.start) });
    parts.push({ text: text.slice(r.start, r.end), isolate: r.isolate });
    pos = r.end;
  }
  if (pos < text.length) parts.push({ text: text.slice(pos) });
  return parts;
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
  if (type === "page" && id) {
    const handle = n.data?.page_handle;
    return typeof handle === "string" && handle ? `/pages/${encodeURIComponent(handle)}` : `/pages/id/${id}`;
  }
  if (type === "group" && id) {
    const handle = n.data?.group_handle;
    return `/groups/${encodeURIComponent(typeof handle === "string" && handle ? handle : id)}`;
  }
  if (n.actor_id) return `/u/id/${n.actor_id}`;
  return "/notifications";
}
