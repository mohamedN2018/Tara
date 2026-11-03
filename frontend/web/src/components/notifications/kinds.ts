// How each notification kind looks and what can be done from it. The server's
// kind registry (services/notification/notifications/registry.py) owns the
// category, channels, grouping and the deep link (`notification.url`); this
// file only owns presentation.
import {
  AtSign,
  Bell,
  Flag,
  Heart,
  type LucideIcon,
  Megaphone,
  MessageCircle,
  MessageSquare,
  Share2,
  ShoppingBag,
  UserCheck,
  UserPlus,
} from "lucide-vue-next";

import type { Notification } from "@/types";

export const KIND_ICONS: Record<string, LucideIcon> = {
  "post.reaction": Heart,
  "post.comment": MessageSquare,
  "comment.reply": MessageSquare,
  "post.share": Share2,
  mention: AtSign,
  "friend.request": UserPlus,
  "friend.accepted": UserCheck,
  follow: UserPlus,
  message: MessageCircle,
  "listing.status": ShoppingBag,
  "listing.inquiry": ShoppingBag,
  "page.follow": Flag,
  "ad.review": Megaphone,
};

export const iconFor = (kind: string): LucideIcon => KIND_ICONS[kind] ?? Bell;

/** Translation key segment for a kind ("post.reaction" -> "post_reaction"). */
export const kindKey = (kind: string) => kind.replace(/\./g, "_");

// The order categories and kinds appear in Settings and the filter chips.
export const CATEGORY_ORDER = ["social", "connections", "messages", "marketplace", "pages", "ads"];

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
  if (n.kind === "message" && !n.body) return t("notifications.kinds.message_attachment", { name });
  const others = othersCount(n);
  const grouped = `notifications.grouped.${segment}`;
  if (others > 0 && te(grouped)) return t(grouped, { name, count: others }, others);
  return t(key, { name, body: n.body });
}

/** Fallback when an old server response has no `url`. */
export function urlFor(n: Notification): string {
  if (n.url && n.url.startsWith("/") && !n.url.startsWith("//")) return n.url;
  const [type, id] = (n.subject_ref || "").split(":");
  if (type === "post" && id) return `/posts/${id}`;
  if (type === "conversation" && id) return `/messages/${id}`;
  if (type === "listing" && id) return `/marketplace/${id}`;
  if (n.actor_id) return `/u/id/${n.actor_id}`;
  return "/notifications";
}
