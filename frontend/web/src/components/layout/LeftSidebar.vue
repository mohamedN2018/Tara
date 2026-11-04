<script setup lang="ts">
import { ChevronDown, ChevronUp } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { legalPath } from "@/lib/legal";
import { useAuthStore } from "@/stores/auth";
import { useChatUnreadStore } from "@/stores/chatUnread";
import { useNotificationStore } from "@/stores/notifications";

import {
  activeNavName,
  loadSidebarExpanded,
  navItems,
  saveSidebarExpanded,
  SIDEBAR_COLLAPSED_COUNT,
  visibleNavItems,
} from "./navItems";
import { cachedShortcuts, type Shortcut } from "./shortcuts";

const { t } = useI18n();
const auth = useAuthStore();
const notifications = useNotificationStore();
const chatUnread = useChatUnreadStore();

const items = computed(() => visibleNavItems(navItems, auth));
const route = useRoute();
// One highlighted entry: Home and Feeds share /home, so the query decides.
const activeName = computed(() => activeNavName(items.value, route.path, route.query));
const expanded = ref(loadSidebarExpanded());
const shown = computed(() => (expanded.value ? items.value : items.value.slice(0, SIDEBAR_COLLAPSED_COUNT)));
const canCollapse = computed(() => items.value.length > SIDEBAR_COLLAPSED_COUNT);

function toggleExpanded() {
  expanded.value = !expanded.value;
  saveSidebarExpanded(expanded.value);
}

const shortcuts = ref<Shortcut[]>([]);
async function loadShortcutList() {
  const owner = auth.account?.id;
  if (!owner) return;
  shortcuts.value = await cachedShortcuts(owner);
}
onMounted(loadShortcutList);
watch(() => auth.account?.id, loadShortcutList);

const profileTo = computed(() =>
  auth.profile?.handle ? `/u/${auth.profile.handle}` : { name: "profile-by-id", params: { id: auth.account?.id ?? "" } },
);
const year = new Date().getFullYear();

function badgeFor(kind?: "notifications" | "messages") {
  if (kind === "notifications") return notifications.unread;
  if (kind === "messages") return chatUnread.conversations;
  return 0;
}

const row =
  "group flex items-center gap-3 rounded-xl px-2 py-2 text-[15px] font-semibold text-gray-800 transition hover:bg-gray-200/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:text-gray-100 dark:hover:bg-gray-800/70";
const active = "bg-brand-50 text-brand-700 dark:bg-brand-950/60 dark:text-brand-200";
</script>

<template>
  <nav class="flex h-full flex-col p-2" :aria-label="t('nav.menu')" data-testid="left-sidebar">
    <!-- Profile shortcut -->
    <RouterLink v-if="auth.profile" :to="profileTo" :class="row" data-testid="sidebar-profile">
      <UserAvatar :name="auth.profile.display_name" :media-id="auth.profile.avatar_media_id" :size="36" />
      <!-- bdi isolates a name in the other script without flipping the row's alignment. -->
      <span class="min-w-0 flex-1 truncate text-start"><bdi>{{ auth.profile.display_name }}</bdi></span>
    </RouterLink>

    <ul class="mt-1 space-y-0.5" data-testid="sidebar-items">
      <li v-for="item in shown" :key="item.name">
        <RouterLink
          :to="item.route"
          :class="[row, activeName === item.name ? active : '']"
          :aria-current="activeName === item.name ? 'page' : undefined"
          :data-testid="`sidebar-${item.name}`"
        >
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full" :class="item.tone">
            <component :is="item.icon" class="h-5 w-5" aria-hidden="true" />
          </span>
          <span class="min-w-0 flex-1 truncate">{{ t(item.labelKey) }}</span>
          <span v-if="badgeFor(item.badge) > 0" class="badge">
            {{ badgeFor(item.badge) > 99 ? "99+" : badgeFor(item.badge) }}
          </span>
        </RouterLink>
      </li>
      <li v-if="canCollapse">
        <button
          type="button"
          :class="[row, 'w-full text-start']"
          :aria-expanded="expanded"
          data-testid="sidebar-see-more"
          @click="toggleExpanded"
        >
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gray-200 text-gray-800 dark:bg-gray-800 dark:text-gray-100">
            <component :is="expanded ? ChevronUp : ChevronDown" class="h-5 w-5" aria-hidden="true" />
          </span>
          <span class="flex-1">{{ expanded ? t("shell.seeLess") : t("shell.seeMore") }}</span>
        </button>
      </li>
    </ul>

    <!-- Your shortcuts: pages you manage and groups you belong to -->
    <section v-if="shortcuts.length" class="mt-2 border-t border-gray-200 pt-3 dark:border-gray-800" aria-labelledby="ls-shortcuts">
      <h2 id="ls-shortcuts" class="px-2 pb-1 text-[15px] font-semibold text-gray-600 dark:text-gray-400">
        {{ t("shell.shortcuts") }}
      </h2>
      <ul class="space-y-0.5" data-testid="sidebar-shortcuts">
        <li v-for="s in shortcuts" :key="`${s.kind}-${s.id}`">
          <RouterLink :to="s.to" :class="row" :title="s.kind === 'page' ? t('shell.shortcutPage') : t('shell.shortcutGroup')">
            <UserAvatar :name="s.name" :media-id="s.mediaId" :size="36" />
            <span class="min-w-0 flex-1 truncate text-start"><bdi>{{ s.name }}</bdi></span>
          </RouterLink>
        </li>
      </ul>
    </section>

    <footer class="mt-auto px-2 pb-2 pt-5 text-xs leading-relaxed text-gray-600 dark:text-gray-400" data-testid="sidebar-footer">
      <RouterLink :to="legalPath('privacy')" class="hover:underline">{{ t("shell.footer.privacy") }}</RouterLink>
      <span aria-hidden="true"> · </span>
      <RouterLink :to="legalPath('terms')" class="hover:underline">{{ t("shell.footer.terms") }}</RouterLink>
      <span aria-hidden="true"> · </span>
      <RouterLink to="/legal/community-standards" class="hover:underline" data-testid="footer-standards">{{ t("menu.items.communityStandards") }}</RouterLink>
      <span aria-hidden="true"> · </span>
      <RouterLink to="/support" class="hover:underline" data-testid="footer-support">{{ t("safety.support.title") }}</RouterLink>
      <span aria-hidden="true"> · </span>
      <RouterLink to="/ads" class="hover:underline">{{ t("nav.ads") }}</RouterLink>
      <span aria-hidden="true"> · </span>
      <span>{{ t("shell.footer.copyright", { name: t("app.name"), year }) }}</span>
    </footer>
  </nav>
</template>
