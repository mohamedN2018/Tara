<script setup lang="ts">
import { LogOut } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { RouteLocationRaw } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import { menuSections } from "@/components/layout/menuCatalog";
import { cachedShortcuts, type Shortcut } from "@/components/layout/shortcuts";
import { legalPath } from "@/lib/legal";
import { useAuthStore } from "@/stores/auth";

/**
 * `/menu`: the mobile menu (the bottom bar's fifth tab). The categorised main
 * menu from menuCatalog.ts (shared with the top bar's MainMenu, so unbuilt or
 * not-permitted items never show), with the profile and "Your shortcuts" on top.
 */
const { t } = useI18n();
const auth = useAuthStore();

const profileTo = computed<RouteLocationRaw>(() => {
  if (auth.profile?.handle) return `/u/${auth.profile.handle}`;
  if (auth.account?.id) return { name: "profile-by-id", params: { id: auth.account.id } };
  return "/settings";
});
const sections = computed(() => menuSections(auth.capabilities, "personal", { profile: profileTo.value }));

const shortcuts = ref<Shortcut[]>([]);
onMounted(async () => {
  if (auth.account?.id) shortcuts.value = await cachedShortcuts(auth.account.id);
});

const year = new Date().getFullYear();
const loggingOut = ref(false);
async function logout() {
  loggingOut.value = true;
  await auth.logout();
}
</script>

<template>
  <AppShell :right="false">
    <div class="mx-auto w-full max-w-2xl space-y-5" data-testid="mobile-menu">
      <h1 class="px-1 font-display text-2xl font-extrabold tracking-tight">{{ t("shell.menu.title") }}</h1>

      <!-- Profile -->
      <RouterLink
        v-if="auth.profile"
        :to="profileTo"
        class="card flex items-center gap-3 p-3 transition hover:border-brand-200 dark:hover:border-brand-900"
        data-testid="menu-profile"
      >
        <UserAvatar :name="auth.profile.display_name" :media-id="auth.profile.avatar_media_id" :size="44" />
        <span class="min-w-0 flex-1">
          <span class="block truncate font-bold" dir="auto">{{ auth.profile.display_name }}</span>
          <span class="block truncate text-sm text-gray-500 dark:text-gray-400">{{ t("shell.menu.viewProfile") }}</span>
        </span>
      </RouterLink>

      <!-- Your shortcuts (pages and groups), scrolled sideways inside their own box -->
      <section v-if="shortcuts.length" aria-labelledby="mm-shortcuts">
        <h2 id="mm-shortcuts" class="px-1 pb-2 text-sm font-semibold text-gray-500 dark:text-gray-400">
          {{ t("shell.menu.shortcuts") }}
        </h2>
        <ul class="-mx-1 flex snap-x gap-2 overflow-x-auto px-1 pb-1" data-testid="menu-shortcuts">
          <li v-for="s in shortcuts" :key="`${s.kind}-${s.id}`" class="w-24 shrink-0 snap-start">
            <RouterLink :to="s.to" class="card flex h-full flex-col items-center gap-2 p-3 text-center">
              <UserAvatar :name="s.name" :media-id="s.mediaId" :size="48" />
              <span class="line-clamp-2 text-xs font-semibold" dir="auto">{{ s.name }}</span>
            </RouterLink>
          </li>
        </ul>
      </section>

      <!-- Every built service, by category -->
      <section v-for="section in sections" :key="section.category" :aria-labelledby="`mm-${section.category}`" :data-testid="`menu-section-${section.category}`">
        <h2 :id="`mm-${section.category}`" class="px-1 pb-2 text-sm font-semibold text-gray-500 dark:text-gray-400">
          {{ t(section.labelKey) }}
        </h2>
        <ul class="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <li v-for="item in section.items" :key="item.id" class="min-w-0">
            <RouterLink
              :to="item.to"
              class="card flex h-full min-w-0 flex-col gap-2 p-3 transition hover:border-brand-200 dark:hover:border-brand-900"
              :data-testid="`menu-item-${item.id}`"
            >
              <span class="flex h-9 w-9 items-center justify-center rounded-full bg-brand-50 text-brand-600 dark:bg-brand-950/60 dark:text-brand-300">
                <component :is="item.icon" class="h-5 w-5" aria-hidden="true" />
              </span>
              <span class="break-words text-sm font-semibold">{{ t(item.labelKey) }}</span>
            </RouterLink>
          </li>
        </ul>
      </section>

      <button
        type="button"
        class="btn w-full bg-gray-200 py-3 text-gray-900 hover:bg-gray-300 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
        :disabled="loggingOut"
        data-testid="menu-logout"
        @click="logout"
      >
        <LogOut class="h-4 w-4" aria-hidden="true" /> {{ t("nav.logout") }}
      </button>

      <p class="px-1 text-xs text-gray-500 dark:text-gray-400">
        <RouterLink :to="legalPath('privacy')" class="hover:underline">{{ t("shell.footer.privacy") }}</RouterLink>
        <span aria-hidden="true"> · </span>
        <RouterLink :to="legalPath('terms')" class="hover:underline">{{ t("shell.footer.terms") }}</RouterLink>
        <span aria-hidden="true"> · </span>
        <span>{{ t("shell.footer.copyright", { name: t("app.name"), year }) }}</span>
      </p>
    </div>
  </AppShell>
</template>
