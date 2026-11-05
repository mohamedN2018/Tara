/**
 * The main menu's catalogue: every service Tara offers or plans, grouped in the
 * eight categories of the social-experience spec, plus the "Create" column.
 *
 * Rules:
 * - `built: false` items are **hidden**, never shown disabled or "coming soon".
 *   Flip `built` only when the route exists in `src/router/index.ts` (a unit
 *   test resolves every built item against the router).
 * - `caps` gates staff items: the item shows when the account holds any one of
 *   the keys (same rule as the router's `meta.caps` / `meta.staff`). The server
 *   still enforces every key; this only decides what the menu shows.
 * - `accountTypes` limits an item to some account types. Identity issues no
 *   account-type claim yet, so every account is "personal" today and no built
 *   item uses it.
 *
 * Shared by the top bar's MainMenu and the mobile `/menu` page: use
 * `menuSections(caps, accountType)` and `createItems(caps, accountType)`.
 */
import {
  Activity,
  Archive,
  BadgeCheck,
  BadgeDollarSign,
  BarChart3,
  Bell,
  BookOpenCheck,
  Bookmark,
  Briefcase,
  Building2,
  CalendarDays,
  CalendarPlus,
  CircleDot,
  Clapperboard,
  Compass,
  Contact,
  FilePlus2,
  FileText,
  Flag,
  HelpCircle,
  History,
  Home,
  Inbox,
  LifeBuoy,
  Library,
  Lock,
  type LucideIcon,
  Megaphone,
  MessageCircle,
  Newspaper,
  PenSquare,
  Radio,
  Settings,
  Shield,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Store,
  Tag,
  User,
  UserCheck,
  Users,
  UsersRound,
  Video,
} from "lucide-vue-next";
import { shallowRef } from "vue";
import type { RouteLocationRaw } from "vue-router";

import { CAPABILITIES, namespaceOf } from "@/lib/capabilities";

export const MENU_CATEGORIES = [
  "account",
  "social",
  "commercial",
  "creator",
  "professional",
  "communication",
  "management",
  "system",
] as const;

export type MenuCategory = (typeof MENU_CATEGORIES)[number];

/** Account types the menu can adapt to. Only "personal" exists today. */
export type AccountType = "personal" | "creator" | "business";

/** Stands for the signed-in account's own profile, resolved per account. */
export const SELF_PROFILE = "@self-profile";

export interface MenuItem {
  id: string;
  /** Where the item goes. `SELF_PROFILE` resolves to the account's profile. */
  route: RouteLocationRaw | typeof SELF_PROFILE;
  /** i18n key of the label. */
  labelKey: string;
  /** i18n key of the one-line description under the label (optional). */
  descKey?: string;
  icon: LucideIcon;
  category: MenuCategory;
  /** Shown only when the account holds any one of these capabilities. */
  caps?: readonly string[];
  /** Shown only to these account types. */
  accountTypes?: readonly AccountType[];
  /** False until the module has a real route; unbuilt items are hidden. */
  built: boolean;
}

/** A "Create" column entry: a real creation flow. */
export interface CreateItem {
  id: string;
  route: RouteLocationRaw;
  labelKey: string;
  icon: LucideIcon;
  caps?: readonly string[];
  accountTypes?: readonly AccountType[];
  built: boolean;
}

export interface ResolvedMenuItem extends Omit<MenuItem, "route"> {
  to: RouteLocationRaw;
}

export interface MenuSection {
  category: MenuCategory;
  labelKey: string;
  items: ResolvedMenuItem[];
}

/** Keys that open the admin console (router `meta.staff`): any moderation.* or admin.* key. */
export const CONSOLE_CAPS: readonly string[] = CAPABILITIES.filter((key) => {
  const ns = namespaceOf(key);
  return ns === "moderation" || ns === "admin";
});

const d = (id: string) => `menu.desc.${id}`;

export const MENU_CATALOG: readonly MenuItem[] = [
  // ---- Your account
  { id: "profile", route: SELF_PROFILE, labelKey: "nav.profile", descKey: d("profile"), icon: User, category: "account", built: true },
  { id: "friends", route: "/friends", labelKey: "nav.friends", descKey: d("friends"), icon: Users, category: "account", built: true },
  { id: "connections", route: "/connections", labelKey: "nav.connections", descKey: d("connections"), icon: UserCheck, category: "account", built: true },
  { id: "saved", route: "/saved", labelKey: "nav.saved", descKey: d("saved"), icon: Bookmark, category: "account", built: true },
  { id: "storyArchive", route: "/stories/archive", labelKey: "stories.archive.title", descKey: "stories.hub.archiveHint", icon: Archive, category: "account", built: true },
  { id: "memories", route: "/memories", labelKey: "menu.items.memories", icon: History, category: "account", built: false },
  { id: "activityLog", route: "/activity", labelKey: "menu.items.activityLog", icon: Activity, category: "account", built: false },

  // ---- Social
  { id: "home", route: "/home", labelKey: "nav.home", descKey: d("home"), icon: Home, category: "social", built: true },
  { id: "explore", route: "/search", labelKey: "nav.explore", descKey: d("explore"), icon: Compass, category: "social", built: true },
  { id: "groups", route: "/groups", labelKey: "nav.groups", descKey: d("groups"), icon: UsersRound, category: "social", built: true },
  { id: "events", route: "/events", labelKey: "nav.events", descKey: d("events"), icon: CalendarDays, category: "social", built: true },
  { id: "pages", route: "/pages", labelKey: "nav.pages", descKey: d("pages"), icon: Flag, category: "social", built: true },
  { id: "followedPages", route: { path: "/pages", query: { tab: "followed" } }, labelKey: "pageHub.manager.followed", descKey: "pageHub.menu.followedDesc", icon: Flag, category: "social", built: true },
  { id: "stories", route: "/stories", labelKey: "menu.items.stories", descKey: "stories.hub.subtitle", icon: CircleDot, category: "social", built: true },
  { id: "reels", route: "/reels", labelKey: "menu.items.reels", descKey: "menu.desc.reels", icon: Clapperboard, category: "social", built: true },
  { id: "videos", route: "/videos", labelKey: "menu.items.videos", icon: Video, category: "social", built: true },
  { id: "feeds", route: { path: "/home", query: { mode: "for_you" } }, labelKey: "postsFeed.feeds.nav", icon: Newspaper, category: "social", built: true },
  { id: "feedPreferences", route: "/feeds/manage", labelKey: "postsFeed.manage.title", icon: SlidersHorizontal, category: "social", built: true },
  { id: "live", route: "/live", labelKey: "menu.items.live", icon: Radio, category: "social", built: false },

  // ---- Commercial
  { id: "marketplace", route: "/marketplace", labelKey: "nav.marketplace", descKey: d("marketplace"), icon: Store, category: "commercial", built: true },
  { id: "myListings", route: { path: "/marketplace", query: { tab: "mine" } }, labelKey: "menu.items.myListings", descKey: d("myListings"), icon: Tag, category: "commercial", built: true },
  { id: "marketplaceInbox", route: { path: "/marketplace", query: { tab: "inbox" } }, labelKey: "commerce.menu.inbox", descKey: "commerce.menu.inboxDesc", icon: Inbox, category: "commercial", built: true },
  { id: "marketplaceChats", route: { path: "/messages", query: { folder: "marketplace" } }, labelKey: "messenger.marketplaceChats", icon: MessageCircle, category: "commercial", built: true },
  { id: "adsManager", route: "/ads", labelKey: "menu.items.adsManager", descKey: d("adsManager"), icon: Megaphone, category: "commercial", built: true },
  { id: "businessCenter", route: "/business", labelKey: "menu.items.businessCenter", icon: Briefcase, category: "commercial", built: false },

  // ---- Creator
  { id: "creatorStudio", route: "/studio", labelKey: "menu.items.creatorStudio", descKey: "studio.home.subtitle", icon: Sparkles, category: "creator", built: true },
  { id: "contentLibrary", route: "/studio/library", labelKey: "menu.items.contentLibrary", icon: Library, category: "creator", built: true },
  { id: "planner", route: "/studio/planner", labelKey: "studio.nav.planner", icon: CalendarDays, category: "creator", built: true },
  { id: "drafts", route: { path: "/studio/library", query: { tab: "drafts" } }, labelKey: "composer.draftsAndScheduled", icon: FileText, category: "creator", built: true },
  { id: "analytics", route: "/studio/insights", labelKey: "menu.items.analytics", icon: BarChart3, category: "creator", built: true },
  { id: "monetization", route: "/studio/monetization", labelKey: "menu.items.monetization", icon: BadgeDollarSign, category: "creator", built: false },

  // ---- Professional
  { id: "professionalProfile", route: "/professional", labelKey: "menu.items.professionalProfile", icon: Contact, category: "professional", built: false },
  { id: "companies", route: "/companies", labelKey: "menu.items.companies", icon: Building2, category: "professional", built: false },
  { id: "jobs", route: "/jobs", labelKey: "menu.items.jobs", icon: Briefcase, category: "professional", built: false },
  { id: "applications", route: "/jobs/applications", labelKey: "menu.items.applications", icon: FileText, category: "professional", built: false },

  // ---- Communication
  { id: "messenger", route: "/messages", labelKey: "nav.messages", descKey: d("messenger"), icon: MessageCircle, category: "communication", built: true },
  { id: "notifications", route: "/notifications", labelKey: "nav.notifications", descKey: d("notifications"), icon: Bell, category: "communication", built: true },
  // Folders of the inbox: `?folder=` (the "/messages/:id?" route would read a path segment as a conversation id).
  { id: "messageRequests", route: { path: "/messages", query: { folder: "requests" } }, labelKey: "menu.items.messageRequests", icon: Inbox, category: "communication", built: true },
  { id: "archived", route: { path: "/messages", query: { folder: "archived" } }, labelKey: "menu.items.archived", icon: Archive, category: "communication", built: true },

  // ---- Management
  { id: "myPages", route: { path: "/pages", query: { tab: "mine" } }, labelKey: "menu.items.myPages", descKey: d("myPages"), icon: Flag, category: "management", built: true },
  { id: "myGroups", route: { path: "/groups", query: { tab: "mine" } }, labelKey: "menu.items.myGroups", descKey: d("myGroups"), icon: UsersRound, category: "management", built: true },
  { id: "pageManagement", route: { path: "/pages", query: { tab: "manage" } }, labelKey: "menu.items.pageManagement", descKey: "pageHub.menu.manageDesc", icon: Flag, category: "management", built: true },
  { id: "groupManagement", route: { path: "/groups", query: { tab: "manage" } }, labelKey: "menu.items.groupManagement", descKey: "pageHub.menu.groupsDesc", icon: Shield, category: "management", built: true },

  // ---- System
  { id: "settings", route: "/settings", labelKey: "nav.settings", descKey: d("settings"), icon: Settings, category: "system", built: true },
  { id: "privacyCenter", route: "/settings/privacy", labelKey: "menu.items.privacyCenter", icon: Lock, category: "system", built: true },
  { id: "securityCenter", route: "/settings/security", labelKey: "menu.items.securityCenter", icon: ShieldCheck, category: "system", built: true },
  { id: "helpCenter", route: "/help", labelKey: "menu.items.helpCenter", icon: HelpCircle, category: "system", built: false },
  { id: "support", route: "/support", labelKey: "menu.items.support", descKey: d("support"), icon: LifeBuoy, category: "system", built: true },
  { id: "communityStandards", route: "/legal/community-standards", labelKey: "menu.items.communityStandards", descKey: d("communityStandards"), icon: BookOpenCheck, category: "system", built: true },
  { id: "adReview", route: "/ads/review", labelKey: "menu.items.adReview", descKey: d("adReview"), icon: BadgeCheck, category: "system", caps: ["ads.review"], built: true },
  { id: "admin", route: "/admin", labelKey: "nav.admin", descKey: d("admin"), icon: Shield, category: "system", caps: CONSOLE_CAPS, built: true },
];

export const CREATE_CATALOG: readonly CreateItem[] = [
  { id: "post", route: "/home", labelKey: "menu.createItems.post", icon: PenSquare, built: true },
  { id: "story", route: { path: "/stories", query: { create: "1" } }, labelKey: "stories.create.title", icon: CircleDot, built: true },
  { id: "reel", route: { path: "/reels", query: { create: "1" } }, labelKey: "reels.create.title", icon: Clapperboard, built: true },
  { id: "page", route: { path: "/pages", query: { create: "1" } }, labelKey: "menu.createItems.page", icon: FilePlus2, built: true },
  { id: "group", route: "/groups/new", labelKey: "menu.createItems.group", icon: UsersRound, built: true },
  { id: "event", route: "/events/new", labelKey: "menu.createItems.event", icon: CalendarPlus, built: true },
  { id: "listing", route: { path: "/marketplace", query: { create: "1" } }, labelKey: "menu.createItems.listing", icon: Store, built: true },
];

type Gated = Pick<MenuItem, "caps" | "accountTypes" | "built"> & { id?: string };

/** Feature flags named `ui.<item id>` decide who sees a menu destination (stores/flags.ts). */
export const UI_FLAG_PREFIX = "ui.";
const flaggedOff = shallowRef<ReadonlySet<string>>(new Set());

/** Item ids switched off for the signed-in account by their `ui.<id>` flag. Staff items never are. */
export function setFlaggedOff(ids: Iterable<string>): void {
  flaggedOff.value = new Set(ids);
}

/** Whether an item shows for this account: built, allowed by caps and by account type. */
export function isVisible(item: Gated, caps: ReadonlySet<string>, accountType: AccountType): boolean {
  if (!item.built) return false;
  if (item.id && !item.caps && flaggedOff.value.has(item.id)) return false;
  if (item.caps && !item.caps.some((key) => caps.has(key))) return false;
  if (item.accountTypes && !item.accountTypes.includes(accountType)) return false;
  return true;
}

const asSet = (caps: Iterable<string>): ReadonlySet<string> => (caps instanceof Set ? caps : new Set(caps));

export interface MenuOptions {
  /** The account's own profile route (defaults to the settings page when unknown). */
  profile?: RouteLocationRaw;
  /** A different catalogue (tests). */
  catalog?: readonly MenuItem[];
}

/** The visible menu, by category in spec order. Categories left empty are dropped. */
export function menuSections(
  caps: Iterable<string>,
  accountType: AccountType = "personal",
  options: MenuOptions = {},
): MenuSection[] {
  const held = asSet(caps);
  const catalog = options.catalog ?? MENU_CATALOG;
  return MENU_CATEGORIES.map((category) => ({
    category,
    labelKey: `menu.sections.${category}`,
    items: catalog
      .filter((item) => item.category === category && isVisible(item, held, accountType))
      .map(({ route, ...rest }) => ({
        ...rest,
        to: route === SELF_PROFILE ? (options.profile ?? "/settings") : route,
      })),
  })).filter((section) => section.items.length > 0);
}

/** The visible "Create" column. */
export function createItems(
  caps: Iterable<string>,
  accountType: AccountType = "personal",
  catalog: readonly CreateItem[] = CREATE_CATALOG,
): CreateItem[] {
  const held = asSet(caps);
  return catalog.filter((item) => isVisible(item, held, accountType));
}

/** Whether a built catalogue item with this id is visible to the account (e.g. help in the profile menu). */
export function hasItem(id: string, caps: Iterable<string>, accountType: AccountType = "personal"): boolean {
  const item = MENU_CATALOG.find((i) => i.id === id);
  return !!item && isVisible(item, asSet(caps), accountType);
}

// ---- search in the menu -----------------------------------------------------------

/**
 * Fold text for matching: lower case, no Arabic diacritics or tatweel, and the
 * common spelling variants (أ/إ/آ → ا, ى → ي, ة → ه) treated as one letter.
 */
export function foldText(text: string): string {
  return text
    .toLowerCase()
    .replace(/[ً-ٰٟـ]/g, "")
    .replace(/[أإآ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .trim();
}

/** Keep the items whose label (or description) contains the query; drop emptied sections. */
export function filterSections(sections: MenuSection[], query: string, translate: (key: string) => string): MenuSection[] {
  const q = foldText(query);
  if (!q) return sections;
  return sections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) =>
        foldText(`${translate(item.labelKey)} ${item.descKey ? translate(item.descKey) : ""}`).includes(q),
      ),
    }))
    .filter((section) => section.items.length > 0);
}

/** The "Create" entries whose label contains the query. */
export function filterCreate(items: CreateItem[], query: string, translate: (key: string) => string): CreateItem[] {
  const q = foldText(query);
  return q ? items.filter((item) => foldText(translate(item.labelKey)).includes(q)) : items;
}
