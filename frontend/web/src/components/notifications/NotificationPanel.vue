<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import NotificationItem from "@/components/notifications/NotificationItem.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { notificationService } from "@/services/notification";
import { useNotificationStore } from "@/stores/notifications";
import type { Notification } from "@/types";

const props = withDefaults(defineProps<{ limit?: number }>(), { limit: 8 });

const { t } = useI18n();
const store = useNotificationStore();

const items = ref<Notification[]>([]);
const loading = ref(true);
const error = ref(false);

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const page = await notificationService.list();
    items.value = page.data.slice(0, props.limit);
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
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

onMounted(load);
defineExpose({ reload: load });
</script>

<template>
  <div class="min-h-24">
    <LoadingSkeleton v-if="loading" :rows="3" />
    <ErrorState v-else-if="error" @retry="load" />
    <EmptyState v-else-if="items.length === 0">{{ t("notifications.empty") }}</EmptyState>
    <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800">
      <li v-for="n in items" :key="n.id">
        <NotificationItem :notification="n" @read="markRead" />
      </li>
    </ul>
  </div>
</template>
