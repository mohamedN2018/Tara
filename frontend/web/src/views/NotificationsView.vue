<script setup lang="ts">
import { CheckCheck, Settings } from "lucide-vue-next";
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AppShell from "@/components/layout/AppShell.vue";
import { FILTER_CATEGORIES } from "@/components/notifications/kinds";
import NotificationItem from "@/components/notifications/NotificationItem.vue";
import { useNotificationActions } from "@/components/notifications/useNotificationActions";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { notificationService } from "@/services/notification";
import { useNotificationStore } from "@/stores/notifications";
import { useToastStore } from "@/stores/toasts";

const { t, te } = useI18n();
const store = useNotificationStore();
const toasts = useToastStore();
const actions = useNotificationActions();

// All / Unread, then one chip per category. Both are answered by the server,
// so unread rows (or a category's rows) beyond the first page are found too.
const unreadOnly = ref(false);
const category = ref("");
// Only categories with a kind that is ever written (the registry leaves the others out).
const liveCategories = ref<Set<string> | null>(null);
const categories = computed(() =>
  liveCategories.value ? FILTER_CATEGORIES.filter((c) => liveCategories.value!.has(c)) : [],
);

const rows = computed(() => (store.filtering ? store.filtered : store.items));
const loading = computed(() => (store.filtering ? store.filteredLoading : store.loading && !store.items.length));
const failed = computed(() => (store.filtering ? store.filteredError : store.error && !store.items.length));
const hasMore = computed(() => (store.filtering ? store.filteredHasMore : store.hasMore));
const loadingMore = computed(() => (store.filtering ? store.filteredLoadingMore : store.loadingMore));

function categoryLabel(c: string): string {
  const key = `notifications.categories.${c}`;
  return te(key) ? t(key) : t(`messenger.notif.categoryNames.${c}`);
}

function apply() {
  void store.setFilter({ unread: unreadOnly.value, category: category.value });
}
function setUnread(value: boolean) {
  unreadOnly.value = value;
  apply();
}
function setCategory(value: string) {
  category.value = category.value === value ? "" : value;
  apply();
}
function retry() {
  if (store.filtering) void store.loadFiltered();
  else void store.load();
}

async function loadMore() {
  const job = store.filtering ? store.loadMoreFiltered() : store.loadMore();
  await job.catch((e) => toasts.error(e));
}

async function markAll() {
  await store.markAllRead().catch((e) => toasts.error(e));
}

const emptyText = computed(() => {
  if (category.value) return t("messenger.notif.emptyCategory");
  return unreadOnly.value ? t("notifications.emptyUnread") : t("notifications.empty");
});

onMounted(() => {
  store.bind();
  // Always fresh on open: rows can have been read or dismissed on another device.
  void store.load();
  void store.refresh();
  notificationService
    .registry()
    .then((r) => (liveCategories.value = new Set(r.kinds.map((k) => k.category))))
    .catch(() => (liveCategories.value = new Set(FILTER_CATEGORIES)));
});
// The dropdown shares the store: leave it unfiltered.
onUnmounted(() => void store.setFilter({ unread: false, category: "" }));
</script>

<template>
  <AppShell>
    <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
      <h1 class="text-2xl font-bold">{{ t("notifications.title") }}</h1>
      <div class="flex items-center gap-1">
        <button class="btn-ghost text-sm" :disabled="store.unread === 0 && !store.hasUnreadLoaded" @click="markAll">
          <CheckCheck class="h-4 w-4" /> {{ t("notifications.markAllRead") }}
        </button>
        <RouterLink to="/settings/notifications" class="icon-btn h-9 w-9" :aria-label="t('notifications.settings')" :title="t('notifications.settings')">
          <Settings class="h-4 w-4" />
        </RouterLink>
      </div>
    </div>

    <div class="mb-2 flex gap-2" role="group" :aria-label="t('notifications.title')">
      <button
        v-for="f in ([false, true] as const)"
        :key="String(f)"
        type="button"
        class="chip"
        :class="unreadOnly === f ? 'chip-active' : ''"
        :aria-pressed="unreadOnly === f"
        :data-testid="`notifications-filter-${f ? 'unread' : 'all'}`"
        @click="setUnread(f)"
      >
        {{ t(`notifications.filters.${f ? "unread" : "all"}`) }}
        <span v-if="f && store.unread > 0" class="badge">{{ store.unread > 99 ? "99+" : store.unread }}</span>
      </button>
    </div>
    <div v-if="categories.length" class="mb-3 flex flex-wrap gap-2" role="group" :aria-label="t('messenger.notif.categories')" data-testid="notification-categories">
      <button
        v-for="c in categories"
        :key="c"
        type="button"
        class="chip shrink-0"
        :class="category === c ? 'chip-active' : ''"
        :aria-pressed="category === c"
        :data-testid="`notification-category-${c}`"
        @click="setCategory(c)"
      >
        {{ categoryLabel(c) }}
      </button>
    </div>

    <LoadingSkeleton v-if="loading" :rows="4" />
    <ErrorState v-else-if="failed" @retry="retry" />
    <EmptyState v-else-if="rows.length === 0">{{ emptyText }}</EmptyState>
    <div v-else>
      <div class="card divide-y divide-gray-100 dark:divide-gray-800" aria-live="polite">
        <NotificationItem
          v-for="n in rows"
          :key="n.id"
          :notification="n"
          :busy="!!store.busy[n.id]"
          @open="actions.open"
          @read="actions.read"
          @dismiss="actions.dismiss"
          @action="actions.act"
          @turn-off="(item, done) => actions.turnOff(item).then(done)"
          @undo-turn-off="(item, done) => actions.undoTurnOff(item).then(done)"
        />
      </div>
    </div>
    <div v-if="hasMore && rows.length" class="mt-4 flex justify-center">
      <button class="btn-ghost" :disabled="loadingMore" @click="loadMore">
        {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
      </button>
    </div>
  </AppShell>
</template>
