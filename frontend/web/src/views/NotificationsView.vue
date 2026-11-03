<script setup lang="ts">
import { CheckCheck, Settings } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AppShell from "@/components/layout/AppShell.vue";
import NotificationItem from "@/components/notifications/NotificationItem.vue";
import { useNotificationActions } from "@/components/notifications/useNotificationActions";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { useNotificationStore } from "@/stores/notifications";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const store = useNotificationStore();
const toasts = useToastStore();
const actions = useNotificationActions();

type Filter = "all" | "unread";
const filter = ref<Filter>("all");
const rows = computed(() => (filter.value === "unread" ? store.items.filter((n) => !n.read_at) : store.items));

async function loadMore() {
  await store.loadMore().catch((e) => toasts.error(e));
}

async function markAll() {
  await store.markAllRead().catch((e) => toasts.error(e));
}

onMounted(() => {
  store.bind();
  // Always fresh on open: rows can have been read or dismissed on another device.
  void store.load();
  void store.refresh();
});
</script>

<template>
  <AppShell>
    <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
      <h1 class="text-xl font-bold">{{ t("notifications.title") }}</h1>
      <div class="flex items-center gap-1">
        <button class="btn-ghost text-sm" :disabled="store.unread === 0 && !store.hasUnreadLoaded" @click="markAll">
          <CheckCheck class="h-4 w-4" /> {{ t("notifications.markAllRead") }}
        </button>
        <RouterLink to="/settings#notifications" class="icon-btn h-9 w-9" :aria-label="t('notifications.settings')" :title="t('notifications.settings')">
          <Settings class="h-4 w-4" />
        </RouterLink>
      </div>
    </div>

    <div class="mb-3 flex gap-2" role="tablist">
      <button
        v-for="f in (['all', 'unread'] as const)"
        :key="f"
        type="button"
        role="tab"
        :aria-selected="filter === f"
        class="chip"
        :class="filter === f ? 'chip-active' : ''"
        @click="filter = f"
      >
        {{ t(`notifications.filters.${f}`) }}
        <span v-if="f === 'unread' && store.unread > 0" class="badge">{{ store.unread > 99 ? "99+" : store.unread }}</span>
      </button>
    </div>

    <LoadingSkeleton v-if="store.loading && !store.items.length" :rows="4" />
    <ErrorState v-else-if="store.error && !store.items.length" @retry="store.load" />
    <EmptyState v-else-if="rows.length === 0">
      {{ filter === "unread" ? t("notifications.emptyUnread") : t("notifications.empty") }}
    </EmptyState>
    <div v-else>
      <div class="card divide-y divide-gray-100 overflow-hidden dark:divide-gray-800" aria-live="polite">
        <NotificationItem
          v-for="n in rows"
          :key="n.id"
          :notification="n"
          :busy="!!store.busy[n.id]"
          @open="actions.open"
          @read="actions.read"
          @dismiss="actions.dismiss"
          @action="actions.act"
        />
      </div>
    </div>
    <div v-if="store.hasMore && store.items.length" class="mt-4 flex justify-center">
      <button class="btn-ghost" :disabled="store.loadingMore" @click="loadMore">
        {{ store.loadingMore ? t("states.loading") : t("feed.loadMore") }}
      </button>
    </div>
  </AppShell>
</template>
