import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import { useAuthStore } from "@/stores/auth";

const routes: RouteRecordRaw[] = [
  { path: "/", name: "landing", component: () => import("@/views/LandingView.vue"), meta: { guest: true } },
  { path: "/login", name: "login", component: () => import("@/views/LoginView.vue"), meta: { guest: true } },
  { path: "/register", name: "register", component: () => import("@/views/RegisterView.vue"), meta: { guest: true } },
  { path: "/forgot-password", name: "forgot-password", component: () => import("@/views/ForgotPasswordView.vue"), meta: { guest: true } },
  { path: "/reset-password", name: "reset-password", component: () => import("@/views/ResetPasswordView.vue"), meta: { guest: true } },
  { path: "/verify-email", name: "verify-email", component: () => import("@/views/VerifyEmailView.vue") },
  { path: "/home", name: "home", component: () => import("@/views/HomeView.vue"), meta: { auth: true } },
  { path: "/u/id/:id", name: "profile-by-id", component: () => import("@/views/ProfileView.vue"), meta: { auth: true } },
  { path: "/u/:handle", name: "profile", component: () => import("@/views/ProfileView.vue"), meta: { auth: true } },
  { path: "/friends", name: "friends", component: () => import("@/views/FriendsView.vue"), meta: { auth: true } },
  { path: "/connections", name: "connections", component: () => import("@/views/ConnectionsView.vue"), meta: { auth: true } },
  { path: "/messages/:id?", name: "messages", component: () => import("@/views/MessagesView.vue"), meta: { auth: true } },
  { path: "/marketplace", name: "marketplace", component: () => import("@/views/MarketplaceView.vue"), meta: { auth: true } },
  { path: "/marketplace/:id", name: "listing", component: () => import("@/views/ListingDetailView.vue"), meta: { auth: true } },
  { path: "/pages", name: "pages", component: () => import("@/views/PagesView.vue"), meta: { auth: true } },
  { path: "/pages/:handle", name: "page", component: () => import("@/views/PageDetailView.vue"), meta: { auth: true } },
  { path: "/ads", name: "ads", component: () => import("@/views/AdsView.vue"), meta: { auth: true } },
  { path: "/ads/campaigns/:id", name: "ad-campaign", component: () => import("@/views/AdCampaignView.vue"), meta: { auth: true } },
  { path: "/ads/review", name: "ad-review", component: () => import("@/views/AdReviewView.vue"), meta: { auth: true, roles: ["admin", "ad_reviewer"] } },
  { path: "/saved", name: "saved", component: () => import("@/views/SavedView.vue"), meta: { auth: true } },
  { path: "/posts/:id", name: "post", component: () => import("@/views/PostDetailView.vue"), meta: { auth: true } },
  { path: "/notifications", name: "notifications", component: () => import("@/views/NotificationsView.vue"), meta: { auth: true } },
  { path: "/search", name: "search", component: () => import("@/views/SearchView.vue"), meta: { auth: true } },
  { path: "/settings", name: "settings", component: () => import("@/views/SettingsView.vue"), meta: { auth: true } },
  { path: "/admin", name: "admin", component: () => import("@/views/AdminView.vue"), meta: { auth: true, staff: true } },
  { path: "/:pathMatch(.*)*", name: "not-found", component: () => import("@/views/NotFoundView.vue") },
];

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
  if (to.meta.staff && !auth.isStaff) {
    return { name: "home" };
  }
  const roles = to.meta.roles as string[] | undefined;
  if (roles && !roles.some((role) => auth.roles.includes(role))) {
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
