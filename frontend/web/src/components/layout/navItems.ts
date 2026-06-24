import {
  Bookmark,
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
}

/** Primary navigation, shared by the sidebar and mobile bar. */
export const navItems: NavItem[] = [
  { name: "home", route: "/home", labelKey: "nav.home", icon: Home },
  { name: "friends", route: "/friends", labelKey: "nav.friends", icon: Users },
  { name: "messages", route: "/messages", labelKey: "nav.messages", icon: MessageCircle },
  { name: "marketplace", route: "/marketplace", labelKey: "nav.marketplace", icon: ShoppingBag },
  { name: "saved", route: "/saved", labelKey: "nav.saved", icon: Bookmark },
  { name: "search", route: "/search", labelKey: "nav.search", icon: Search },
  { name: "settings", route: "/settings", labelKey: "nav.settings", icon: Settings },
];
