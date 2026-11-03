import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

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
  { path: "/marketplace/:id", name: "listing", component: () => import("@/views/ListingDetailView.vue"), meta: { auth: true } },
  { path: "/pages", name: "pages", component: () => import("@/views/PagesView.vue"), meta: { auth: true } },
  { path: "/pages/:handle", name: "page", component: () => import("@/views/PageDetailView.vue"), meta: { auth: true } },
  { path: "/ads", name: "ads", component: () => import("@/views/AdsView.vue"), meta: { auth: true } },
  { path: "/ads/campaigns/:id", name: "ad-campaign", component: () => import("@/views/AdCampaignView.vue"), meta: { auth: true } },
  { path: "/ads/review", name: "ad-review", component: () => import("@/views/AdReviewView.vue"), meta: { auth: true, caps: ["ads.review"] } },
  { path: "/saved", name: "saved", component: () => import("@/views/SavedView.vue"), meta: { auth: true } },
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
  { path: "/settings", name: "settings", component: () => import("@/views/SettingsView.vue"), meta: { auth: true } },
  { path: "/admin", name: "admin", component: () => import("@/views/AdminView.vue"), meta: { auth: true, staff: true } },
  { path: "/admin/capabilities", name: "admin-capabilities", component: () => import("@/views/AdminCapabilitiesView.vue"), meta: { auth: true, staff: true, caps: ["admin.capabilities.manage"] } },
  { path: "/admin/audit", name: "admin-audit", component: () => import("@/views/AdminAuditView.vue"), meta: { auth: true, staff: true, caps: ["admin.audit.view"] } },
  { path: "/admin/monitor", name: "admin-monitor", component: () => import("@/views/AdminMonitorView.vue"), meta: { auth: true, staff: true, caps: ["admin.monitor.view"] } },
  { path: "/admin/users", name: "admin-users", component: () => import("@/views/AdminUsersView.vue"), meta: { auth: true, staff: true, caps: ["admin.users.view"] } },
  { path: "/admin/users/:id", name: "admin-user", component: () => import("@/views/AdminUserView.vue"), meta: { auth: true, staff: true, caps: ["admin.users.view"] } },
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
  scrollBehavior: () => ({ top: 0 }),
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
