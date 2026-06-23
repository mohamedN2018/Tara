import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import { useAuthStore } from "@/stores/auth";

const routes: RouteRecordRaw[] = [
  { path: "/", name: "landing", component: () => import("@/views/LandingView.vue"), meta: { guest: true } },
  { path: "/login", name: "login", component: () => import("@/views/LoginView.vue"), meta: { guest: true } },
  { path: "/register", name: "register", component: () => import("@/views/RegisterView.vue"), meta: { guest: true } },
  { path: "/home", name: "home", component: () => import("@/views/HomeView.vue"), meta: { auth: true } },
  { path: "/u/:handle", name: "profile", component: () => import("@/views/ProfileView.vue"), meta: { auth: true } },
  { path: "/friends", name: "friends", component: () => import("@/views/FriendsView.vue"), meta: { auth: true } },
  { path: "/messages/:id?", name: "messages", component: () => import("@/views/MessagesView.vue"), meta: { auth: true } },
  { path: "/marketplace", name: "marketplace", component: () => import("@/views/MarketplaceView.vue"), meta: { auth: true } },
  { path: "/marketplace/:id", name: "listing", component: () => import("@/views/ListingDetailView.vue"), meta: { auth: true } },
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
  return true;
});
