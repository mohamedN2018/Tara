import {
  Bell,
  Bookmark,
  CalendarDays,
  Flag,
  Home,
  type LucideIcon,
  Megaphone,
  Newspaper,
  MessageCircle,
  Search,
  Settings,
  Shield,
  ShoppingBag,
  Sparkles,
  UserCheck,
  Users,
  UsersRound,
  Video,
} from "lucide-vue-next";

export interface NavItem {
  name: string;
  route: string;
  labelKey: string;
  icon: LucideIcon;
  /** Which live counter, if any, shows as a badge. */
  badge?: "notifications" | "messages";
  /** Tailwind classes for the round icon tile (Tara brand family). */
  tone?: string;
  /** Shown only to staff (the console checks capabilities again, and the API enforces them). */
  staff?: boolean;
}

// Tile colours: the brand family only (purple, violet, pink, lavender on indigo).
const PURPLE = "bg-brand-100 text-brand-700 dark:bg-brand-950/70 dark:text-brand-300";
const VIOLET = "bg-brand-50 text-brand-500 dark:bg-brand-900/50 dark:text-brand-300";
const PINK = "bg-accent-100 text-accent-700 dark:bg-accent-900/40 dark:text-accent-300";
const LAVENDER = "bg-lavender text-ink dark:bg-gray-800 dark:text-lavender";

/**
 * Sidebar navigation, in the order the reference layout uses. Only built modules
 * are listed: Memories, Reels, Video, Live, Gaming, Creator Studio, Professional,
 * Business Center and Help join this list when they exist (never shown disabled).
 */
export const navItems: NavItem[] = [
  { name: "friends", route: "/friends", labelKey: "nav.friends", icon: Users, tone: PURPLE },
  { name: "saved", route: "/saved", labelKey: "nav.saved", icon: Bookmark, tone: PINK },
  { name: "groups", route: "/groups", labelKey: "nav.groups", icon: UsersRound, tone: VIOLET },
  { name: "videos", route: "/videos", labelKey: "menu.items.videos", icon: Video, tone: PINK },
  { name: "marketplace", route: "/marketplace", labelKey: "nav.marketplace", icon: ShoppingBag, tone: PURPLE },
  // Feeds: Home sorted For you / Latest / Favorites / Following, plus feed preferences.
  { name: "feeds", route: "/home?mode=for_you", labelKey: "postsFeed.feeds.nav", icon: Newspaper, tone: VIOLET },
  { name: "home", route: "/home", labelKey: "nav.home", icon: Home, tone: LAVENDER },
  { name: "events", route: "/events", labelKey: "nav.events", icon: CalendarDays, tone: PINK },
  { name: "pages", route: "/pages", labelKey: "nav.pages", icon: Flag, tone: VIOLET },
  { name: "messages", route: "/messages", labelKey: "nav.messages", icon: MessageCircle, badge: "messages", tone: PURPLE },
  { name: "notifications", route: "/notifications", labelKey: "nav.notifications", icon: Bell, badge: "notifications", tone: PINK },
  { name: "search", route: "/search", labelKey: "nav.explore", icon: Search, tone: LAVENDER },
  { name: "connections", route: "/connections", labelKey: "nav.connections", icon: UserCheck, tone: VIOLET },
  { name: "ads", route: "/ads", labelKey: "nav.ads", icon: Megaphone, tone: PINK },
  { name: "studio", route: "/studio", labelKey: "menu.items.creatorStudio", icon: Sparkles, tone: VIOLET },
  { name: "settings", route: "/settings", labelKey: "nav.settings", icon: Settings, tone: LAVENDER },
  { name: "admin", route: "/admin", labelKey: "nav.admin", icon: Shield, tone: PURPLE, staff: true },
];

/** The items this viewer may see, in order. */
export function visibleNavItems(items: readonly NavItem[], viewer: { isStaff: boolean }): NavItem[] {
  return items.filter((item) => !item.staff || viewer.isStaff);
}

/**
 * The one item to highlight for the current location. Items that share a path
 * (Home and Feeds are both /home) are told apart by query: an item whose route
 * carries a query (`?mode=`) wins when those keys are present, the plain item
 * otherwise, so two entries never light up together.
 */
export function activeNavName(
  items: readonly NavItem[],
  path: string,
  query: Record<string, unknown>,
): string | null {
  const split = (r: string) => {
    const [p, q = ""] = r.split("?");
    return { p, keys: [...new URLSearchParams(q).keys()] };
  };
  const same = items.map((item) => ({ item, ...split(item.route) })).filter((x) => x.p === path);
  const withQuery = same.find((x) => x.keys.length && x.keys.every((k) => query[k] !== undefined && query[k] !== null));
  if (withQuery) return withQuery.item.name;
  return same.find((x) => !x.keys.length)?.item.name ?? null;
}

/** How many items show before "See more". */
export const SIDEBAR_COLLAPSED_COUNT = 8;

export const SIDEBAR_EXPANDED_KEY = "tara.sidebar.expanded";

/** Whether the viewer last left the sidebar expanded (false when storage is blocked). */
export function loadSidebarExpanded(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_EXPANDED_KEY) === "1";
  } catch {
    return false;
  }
}

export function saveSidebarExpanded(expanded: boolean): void {
  try {
    if (expanded) localStorage.setItem(SIDEBAR_EXPANDED_KEY, "1");
    else localStorage.removeItem(SIDEBAR_EXPANDED_KEY);
  } catch {
    // Storage blocked: the choice lasts for this page.
  }
}
