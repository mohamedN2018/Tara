import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import { LEGACY_HASH } from "@/components/settings/sections";
import { useAuthStore } from "@/stores/auth";

const routes: RouteRecordRaw[] = [
  { path: "/", name: "landing", component: () => import("@/views/LandingView.vue"), meta: { guest: true } },
  { path: "/login", name: "login", component: () => import("@/views/LoginView.vue"), meta: { guest: true } },
  { path: "/register", name: "register", component: () => import("@/views/RegisterView.vue"), meta: { guest: true } },
  { path: "/forgot-password", name: "forgot-password", component: () => import("@/views/ForgotPasswordView.vue"), meta: { guest: true } },
  { path: "/reset-password", name: "reset-password", component: () => import("@/views/ResetPasswordView.vue"), meta: { guest: true } },
  { path: "/verify-email", name: "verify-email", component: () => import("@/views/VerifyEmailView.vue") },
  { path: "/confirm-email", name: "confirm-email", component: () => import("@/views/ConfirmEmailView.vue") },
  { path: "/home", name: "home", component: () => import("@/views/HomeView.vue"), meta: { auth: true } },
  { path: "/u/id/:id", name: "profile-by-id", component: () => import("@/views/ProfileView.vue"), meta: { auth: true } },
  { path: "/u/:handle", name: "profile", component: () => import("@/views/ProfileView.vue"), meta: { auth: true } },
  { path: "/friends", name: "friends", component: () => import("@/views/FriendsView.vue"), meta: { auth: true } },
  { path: "/connections", name: "connections", component: () => import("@/views/ConnectionsView.vue"), meta: { auth: true } },
  { path: "/messages/:id?", name: "messages", component: () => import("@/views/MessagesView.vue"), meta: { auth: true } },
  { path: "/marketplace", name: "marketplace", component: () => import("@/views/MarketplaceView.vue"), meta: { auth: true } },
  { path: "/marketplace/compare", name: "marketplace-compare", component: () => import("@/views/MarketplaceCompareView.vue"), meta: { auth: true } },
  { path: "/marketplace/sellers/:id", name: "marketplace-seller", component: () => import("@/views/MarketplaceSellerView.vue"), meta: { auth: true } },
  { path: "/marketplace/:id", name: "listing", component: () => import("@/views/ListingDetailView.vue"), meta: { auth: true } },
  { path: "/pages", name: "pages", component: () => import("@/views/PagesView.vue"), meta: { auth: true } },
  // Links that only carry a page id (follows, saved items, page posts) resolve to the handle route.
  { path: "/pages/id/:id/inbox", name: "page-inbox", component: () => import("@/views/PageInboxView.vue"), meta: { auth: true } },
  { path: "/pages/id/:id", name: "page-by-id", component: () => import("@/views/PageByIdView.vue"), meta: { auth: true } },
  { path: "/pages/:handle", name: "page", component: () => import("@/views/PageDetailView.vue"), meta: { auth: true } },
  { path: "/ads", name: "ads", component: () => import("@/views/AdsView.vue"), meta: { auth: true } },
  { path: "/ads/campaigns/:id", name: "ad-campaign", component: () => import("@/views/AdCampaignView.vue"), meta: { auth: true } },
  { path: "/ads/review", name: "ad-review", component: () => import("@/views/AdReviewView.vue"), meta: { auth: true, caps: ["ads.review"] } },
  { path: "/saved", name: "saved", component: () => import("@/views/SavedView.vue"), meta: { auth: true } },
  // Stories (T9): the hub, my archive, and one story (a notification link).
  { path: "/stories", name: "stories", component: () => import("@/views/StoriesView.vue"), meta: { auth: true } },
  { path: "/stories/archive", name: "story-archive", component: () => import("@/views/StoryArchiveView.vue"), meta: { auth: true } },
  { path: "/stories/:id", name: "story", component: () => import("@/views/StoriesView.vue"), meta: { auth: true } },
  // T4: video posts and feed preferences (snoozes).
  { path: "/videos", name: "videos", component: () => import("@/views/VideosView.vue"), meta: { auth: true } },
  // Reels (5.8): short vertical videos in a snap pager, apart from /videos.
  { path: "/reels", name: "reels", component: () => import("@/views/ReelsView.vue"), meta: { auth: true } },
  { path: "/reels/:id", name: "reel", component: () => import("@/views/ReelsView.vue"), meta: { auth: true } },
  { path: "/feeds/manage", name: "feed-preferences", component: () => import("@/views/FeedPreferencesView.vue"), meta: { auth: true } },
  // Creator studio (T8): its own layout with nested pages. Drafts deep links land in the library.
  {
    path: "/studio",
    component: () => import("@/components/studio/StudioLayout.vue"),
    meta: { auth: true },
    children: [
      { path: "", name: "studio", component: () => import("@/views/studio/StudioHomeView.vue"), meta: { auth: true } },
      { path: "library", name: "studio-library", component: () => import("@/views/studio/StudioLibraryView.vue"), meta: { auth: true } },
      { path: "planner", name: "studio-planner", component: () => import("@/views/studio/StudioPlannerView.vue"), meta: { auth: true } },
      { path: "insights", name: "studio-insights", component: () => import("@/views/studio/StudioInsightsView.vue"), meta: { auth: true } },
      { path: "engagement", name: "studio-engagement", component: () => import("@/views/studio/StudioEngagementView.vue"), meta: { auth: true } },
    ],
  },
  { path: "/posts/drafts", name: "drafts", redirect: { path: "/studio/library", query: { tab: "drafts" } } },
  { path: "/posts/drafts/:id", name: "draft", redirect: (to) => ({ path: "/studio/library", query: { tab: "drafts", edit: String(to.params.id) } }) },
  { path: "/posts/:id", name: "post", component: () => import("@/views/PostDetailView.vue"), meta: { auth: true } },
  { path: "/events", name: "events", component: () => import("@/views/EventsView.vue"), meta: { auth: true } },
  { path: "/events/new", name: "event-new", component: () => import("@/views/EventFormView.vue"), meta: { auth: true } },
  { path: "/events/:id/edit", name: "event-edit", component: () => import("@/views/EventFormView.vue"), meta: { auth: true } },
  { path: "/events/:id", name: "event", component: () => import("@/views/EventDetailView.vue"), meta: { auth: true } },
  { path: "/groups", name: "groups", component: () => import("@/views/GroupsView.vue"), meta: { auth: true } },
  { path: "/groups/new", name: "group-new", component: () => import("@/views/GroupFormView.vue"), meta: { auth: true } },
  { path: "/groups/:handle/manage", name: "group-manage", component: () => import("@/views/GroupManageView.vue"), meta: { auth: true } },
  { path: "/groups/:handle", name: "group", component: () => import("@/views/GroupDetailView.vue"), meta: { auth: true } },
  { path: "/notifications", name: "notifications", component: () => import("@/views/NotificationsView.vue"), meta: { auth: true } },
  { path: "/search", name: "search", component: () => import("@/views/SearchView.vue"), meta: { auth: true } },
  // Settings & privacy centre (T1): one route, a section per page. Old one-page
  // anchors (/settings#notifications) land on the section that holds them.
  {
    path: "/settings/:section(account|privacy|security|notifications|content|display)?",
    name: "settings",
    component: () => import("@/views/SettingsView.vue"),
    meta: { auth: true },
    beforeEnter: (to) => {
      const legacy = !to.params.section && to.hash ? LEGACY_HASH[to.hash.slice(1)] : undefined;
      return legacy ? { name: "settings", params: { section: legacy.section }, hash: legacy.hash ?? "", query: to.query } : true;
    },
  },
  // The activity log: the signed-in account's own posts, comments, reactions, saves and searches.
  { path: "/settings/activity-log", name: "activity-log", component: () => import("@/views/ActivityLogView.vue"), meta: { auth: true } },
  // The privacy center (T2's profile and field visibility included) is the settings centre's Privacy section.
  // The mobile menu (the fifth bottom tab): the categorised main menu as a page.
  { path: "/menu", name: "menu", component: () => import("@/views/MobileMenuView.vue"), meta: { auth: true } },
  // Public legal pages: readable signed in or out (neither `auth` nor `guest`).
  { path: "/legal/:doc(terms|privacy)", name: "legal", component: () => import("@/views/LegalView.vue") },
  { path: "/admin", name: "admin", component: () => import("@/views/AdminView.vue"), meta: { auth: true, staff: true } },
  { path: "/admin/capabilities", name: "admin-capabilities", component: () => import("@/views/AdminCapabilitiesView.vue"), meta: { auth: true, staff: true, caps: ["admin.capabilities.manage"] } },
  { path: "/admin/audit", name: "admin-audit", component: () => import("@/views/AdminAuditView.vue"), meta: { auth: true, staff: true, caps: ["admin.audit.view"] } },
  { path: "/admin/monitor", name: "admin-monitor", component: () => import("@/views/AdminMonitorView.vue"), meta: { auth: true, staff: true, caps: ["admin.monitor.view"] } },
  { path: "/admin/users", name: "admin-users", component: () => import("@/views/AdminUsersView.vue"), meta: { auth: true, staff: true, caps: ["admin.users.view"] } },
  { path: "/admin/users/:id", name: "admin-user", component: () => import("@/views/AdminUserView.vue"), meta: { auth: true, staff: true, caps: ["admin.users.view"] } },
  // Moderator console sections and the member's Support inbox (track T7).
  { path: "/admin/moderation", name: "admin-moderation", component: () => import("@/views/AdminModerationView.vue"), meta: { auth: true, staff: true, caps: ["moderation.case.view", "moderation.appeal.view"] } },
  { path: "/admin/roles", name: "admin-roles", component: () => import("@/views/AdminRolesView.vue"), meta: { auth: true, staff: true, caps: ["admin.roles.manage"] } },
  { path: "/admin/flags", name: "admin-flags", component: () => import("@/views/AdminFlagsView.vue"), meta: { auth: true, staff: true, caps: ["admin.flags.manage"] } },
  { path: "/admin/support", name: "admin-support", component: () => import("@/views/AdminSupportView.vue"), meta: { auth: true, staff: true, caps: ["moderation.case.view"] } },
  { path: "/admin/notices", name: "admin-notices", component: () => import("@/views/AdminNoticesView.vue"), meta: { auth: true, staff: true, caps: ["admin.notices.send"] } },
  { path: "/support", name: "support", component: () => import("@/views/SupportView.vue"), meta: { auth: true } },
  { path: "/legal/community-standards", name: "community-standards", component: () => import("@/views/CommunityStandardsView.vue") },
  { path: "/:pathMatch(.*)*", name: "not-found", component: () => import("@/views/NotFoundView.vue") },
];

/** Staff gates of a route: `staff` needs any console capability, `caps` any one of the listed keys. */
export function staffAccessAllowed(
  meta: { staff?: unknown; caps?: unknown; roles?: unknown },
  auth: { isStaff: boolean; roles: string[]; canAny: (caps: readonly string[]) => boolean },
): boolean {
  if (meta.staff && !auth.isStaff) return false;
  const caps = meta.caps as string[] | undefined;
  if (caps && !auth.canAny(caps)) return false;
  const roles = meta.roles as string[] | undefined;
  return !roles || roles.some((role) => auth.roles.includes(role));
}

export const router = createRouter({
  history: createWebHistory(),
  routes,
  // A hash scrolls to its element (settings anchors) when it exists; a hash
  // change within one page that names no element (a tab) keeps the position.
  scrollBehavior: (to, from, saved) => {
    if (saved) return saved;
    if (to.hash) {
      let el: Element | null = null;
      try {
        el = document.querySelector(to.hash);
      } catch {
        el = null; // not a valid selector
      }
      if (el) return { el: to.hash, top: 72, behavior: "smooth" };
      if (to.path === from.path) return false;
    }
    return { top: 0 };
  },
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (!auth.ready) await auth.bootstrap();

  if (to.meta.auth && !auth.isAuthenticated) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.meta.guest && auth.isAuthenticated) {
    return { name: "home" };
  }
  if (!staffAccessAllowed(to.meta, auth)) {
    return { name: "home" };
  }
  return true;
});

// After a deploy, an open tab may ask for chunks that no longer exist. Reload to
// pick up the new build, at most once, so a real outage can't cause a reload loop.
const CHUNK_RELOAD_KEY = "tara.chunkReloadAt";
const CHUNK_ERROR =
  /dynamically imported module|Importing a module script failed|error loading dynamically imported|Loading (CSS )?chunk/i;

router.onError((error: unknown, to) => {
  if (!CHUNK_ERROR.test(error instanceof Error ? error.message : String(error))) return;
  const last = Number(sessionStorage.getItem(CHUNK_RELOAD_KEY) ?? 0);
  if (Date.now() - last < 10_000) return;
  sessionStorage.setItem(CHUNK_RELOAD_KEY, String(Date.now()));
  window.location.assign(to.fullPath);
});
