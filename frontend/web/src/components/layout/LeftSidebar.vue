<script setup lang="ts">
import { Megaphone, PenSquare, Shield } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { useAuthStore } from "@/stores/auth";
import { useNotificationStore } from "@/stores/notifications";
import { useUiStore } from "@/stores/ui";

import { navItems } from "./navItems";

const { t } = useI18n();
const router = useRouter();
const auth = useAuthStore();
const ui = useUiStore();
const notifications = useNotificationStore();

function badgeFor(kind?: "notifications") {
  if (kind === "notifications") return notifications.unread;
  return 0;
}

function createPost() {
  ui.requestCompose();
  router.push("/home");
}
</script>

<template>
  <nav class="flex h-full flex-col gap-1 p-3" :aria-label="t('nav.home')">
    <!-- Profile shortcut -->
    <RouterLink
      v-if="auth.profile"
      :to="`/u/${auth.profile.handle}`"
      class="mb-2 flex items-center gap-3 rounded-2xl border border-gray-200/70 bg-white p-2.5 transition hover:border-brand-200 dark:border-gray-800 dark:bg-gray-900 dark:hover:border-brand-900"
    >
      <span class="avatar-ring shrink-0">
        <span class="block rounded-full bg-white p-[2px] dark:bg-gray-900">
          <UserAvatar :name="auth.profile.display_name" :media-id="auth.profile.avatar_media_id" :size="38" />
        </span>
      </span>
      <span class="min-w-0">
        <span class="block truncate text-sm font-bold" dir="auto">{{ auth.profile.display_name }}</span>
        <span class="block truncate text-xs text-gray-500 dark:text-gray-400" dir="ltr">@{{ auth.profile.handle }}</span>
      </span>
    </RouterLink>

    <RouterLink
      v-for="item in navItems"
      :key="item.name"
      :to="item.route"
      class="nav-item group"
      active-class="nav-item-active"
    >
      <component :is="item.icon" class="h-5 w-5 shrink-0" />
      <span class="flex-1">{{ t(item.labelKey) }}</span>
      <span v-if="badgeFor(item.badge) > 0" class="badge">
        {{ badgeFor(item.badge) > 99 ? "99+" : badgeFor(item.badge) }}
      </span>
    </RouterLink>

    <RouterLink to="/ads" class="nav-item" active-class="nav-item-active">
      <Megaphone class="h-5 w-5 shrink-0" />
      <span class="flex-1">{{ t("nav.ads") }}</span>
    </RouterLink>

    <RouterLink v-if="auth.isStaff" to="/admin" class="nav-item" active-class="nav-item-active">
      <Shield class="h-5 w-5 shrink-0" />
      <span class="flex-1">{{ t("nav.admin") }}</span>
    </RouterLink>

    <button type="button" class="btn-gradient mt-3 w-full py-3" @click="createPost">
      <PenSquare class="h-4 w-4" />
      {{ t("nav.createPost") }}
    </button>

    <p class="mt-auto px-3 pt-6 text-xs text-gray-400 dark:text-gray-500">
      <span class="font-semibold text-gray-500 dark:text-gray-400">{{ t("app.name") }}</span> · {{ t("app.tagline") }} · © 2026
    </p>
  </nav>
</template>
