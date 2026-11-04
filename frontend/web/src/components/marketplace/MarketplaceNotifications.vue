<script setup lang="ts">
// The marketplace's own notifications: the registry's "marketplace" category
// (listing status changes, buyer inquiries...), newest first. Reading and
// dismissing go to the notification service like on the Notifications page.
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import NotificationItem from "@/components/notifications/NotificationItem.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { notificationService } from "@/services/notification";
import { useNotificationStore } from "@/stores/notifications";
import { useToastStore } from "@/stores/toasts";
import type { Notification } from "@/types";

const { t } = useI18n();
const store = useNotificationStore();
const toasts = useToastStore();

const items = ref<Notification[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);

async function load(more = false) {
  if (more) loadingMore.value = true;
  else loading.value = true;
  error.value = false;
  try {
    const page = await notificationService.list({
      category: "marketplace",
      cursor: more ? (cursor.value ?? undefined) : undefined,
    });
    items.value = more ? [...items.value, ...page.data] : page.data;
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch (e) {
    if (more) toasts.error(e);
    else error.value = true;
  } finally {
    loading.value = false;
    loadingMore.value = false;
  }
}

async function read(id: string) {
  const n = items.value.find((i) => i.id === id);
  if (!n || n.read_at) return;
  n.read_at = new Date().toISOString();
  try {
    // Through the shared store when it holds the row, so the badge follows.
    if (store.items.some((i) => i.id === id)) await store.markRead(id);
    else await notificationService.markRead(id);
  } catch (e) {
    n.read_at = null;
    toasts.error(e);
  }
}

async function dismiss(id: string) {
  const before = items.value;
  items.value = items.value.filter((i) => i.id !== id);
  try {
    if (store.items.some((i) => i.id === id)) await store.remove(id);
    else await notificationService.remove(id);
  } catch (e) {
    items.value = before;
    toasts.error(e);
  }
}

onMounted(() => load());
</script>

<template>
  <section class="card p-2 sm:p-3" data-testid="market-notifications">
    <h2 class="px-2 pb-2 pt-1 text-lg font-bold">{{ t("commerce.nav.notifications") }}</h2>
    <LoadingSkeleton v-if="loading" :rows="3" />
    <ErrorState v-else-if="error" @retry="load()" />
    <EmptyState v-else-if="!items.length">{{ t("commerce.notifications.empty") }}</EmptyState>
    <ul v-else class="space-y-1">
      <li v-for="n in items" :key="n.id">
        <NotificationItem :notification="n" @open="read(n.id)" @read="read" @dismiss="dismiss" />
      </li>
    </ul>
    <div v-if="hasMore" class="mt-3 flex justify-center">
      <button class="btn-ghost" :disabled="loadingMore" @click="load(true)">
        {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
      </button>
    </div>
  </section>
</template>
