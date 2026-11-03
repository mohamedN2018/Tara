import {
  Bell,
  Bookmark,
  CalendarDays,
  Flag,
  Home,
  type LucideIcon,
  MessageCircle,
  Search,
  Settings,
  ShoppingBag,
  Users,
} from "lucide-vue-next";

export interface NavItem {
  name: string;
  route: string;
  labelKey: string;
  icon: LucideIcon;
  /** Which live counter, if any, shows as a badge. */
  badge?: "notifications" | "messages";
}

/** Primary navigation for the sidebar (and the mobile drawer). */
export const navItems: NavItem[] = [
  { name: "home", route: "/home", labelKey: "nav.home", icon: Home },
  { name: "friends", route: "/friends", labelKey: "nav.friends", icon: Users },
  { name: "messages", route: "/messages", labelKey: "nav.messages", icon: MessageCircle, badge: "messages" },
  { name: "notifications", route: "/notifications", labelKey: "nav.notifications", icon: Bell, badge: "notifications" },
  { name: "search", route: "/search", labelKey: "nav.explore", icon: Search },
  { name: "pages", route: "/pages", labelKey: "nav.pages", icon: Flag },
  { name: "events", route: "/events", labelKey: "nav.events", icon: CalendarDays },
  { name: "marketplace", route: "/marketplace", labelKey: "nav.marketplace", icon: ShoppingBag },
  { name: "saved", route: "/saved", labelKey: "nav.saved", icon: Bookmark },
  { name: "settings", route: "/settings", labelKey: "nav.settings", icon: Settings },
];
