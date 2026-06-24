<script setup lang="ts">
import { CheckCheck } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AppShell from "@/components/layout/AppShell.vue";
import NotificationItem from "@/components/notifications/NotificationItem.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { notificationService } from "@/services/notification";
import { useNotificationStore } from "@/stores/notifications";
import type { Notification } from "@/types";

const { t } = useI18n();
const store = useNotificationStore();

const items = ref<Notification[]>([]);
const loading = ref(true);
const error = ref(false);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loadingMore = ref(false);

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const page = await notificationService.list();
    items.value = page.data;
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

async function loadMore() {
  if (!cursor.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await notificationService.list(cursor.value);
    items.value.push(...page.data);
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch {
    /* keep what we have */
  } finally {
    loadingMore.value = false;
  }
}

async function markRead(id: string) {
  const item = items.value.find((n) => n.id === id);
  if (!item || item.read_at) return;
  item.read_at = new Date().toISOString();
  store.unread = Math.max(0, store.unread - 1);
  try {
    await notificationService.markRead(id);
  } catch {
    item.read_at = null;
  }
}

async function markAll() {
  items.value.forEach((n) => (n.read_at = n.read_at ?? new Date().toISOString()));
  store.clear();
  await notificationService.markAllRead().catch(() => {});
}

onMounted(load);
</script>

<template>
  <AppShell>
    <div class="mb-4 flex items-center justify-between">
      <h1 class="text-xl font-bold">{{ t("notifications.title") }}</h1>
      <button class="btn-ghost text-sm" @click="markAll">
        <CheckCheck class="h-4 w-4" /> {{ t("notifications.markAllRead") }}
      </button>
    </div>

    <LoadingSkeleton v-if="loading" :rows="4" />
    <ErrorState v-else-if="error" @retry="load" />
    <EmptyState v-else-if="items.length === 0">{{ t("notifications.empty") }}</EmptyState>
    <div v-else>
      <div class="card divide-y divide-gray-100 overflow-hidden dark:divide-gray-800">
        <NotificationItem
          v-for="n in items"
          :key="n.id"
          :notification="n"
          @read="markRead"
        />
      </div>
      <div v-if="hasMore" class="mt-4 flex justify-center">
        <button class="btn-ghost" :disabled="loadingMore" @click="loadMore">
          {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
        </button>
      </div>
    </div>
  </AppShell>
</template>
