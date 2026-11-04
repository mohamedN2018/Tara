<script setup lang="ts">
// The navbar dropdown: the newest rows of the shared live list.
import { computed, onMounted } from "vue";
import { useI18n } from "vue-i18n";

import NotificationItem from "@/components/notifications/NotificationItem.vue";
import { useNotificationActions } from "@/components/notifications/useNotificationActions";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { useNotificationStore } from "@/stores/notifications";

const props = withDefaults(defineProps<{ limit?: number }>(), { limit: 8 });
const emit = defineEmits<{ navigate: [] }>();

const { t } = useI18n();
const store = useNotificationStore();
const actions = useNotificationActions();

const rows = computed(() => store.items.slice(0, props.limit));

onMounted(() => {
  store.bind();
  void store.ensureLoaded();
});
</script>

<template>
  <div class="min-h-24">
    <LoadingSkeleton v-if="store.loading && !store.items.length" :rows="3" />
    <ErrorState v-else-if="store.error && !store.items.length" @retry="store.load" />
    <EmptyState v-else-if="!rows.length">{{ t("notifications.empty") }}</EmptyState>
    <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800" aria-live="polite">
      <li v-for="n in rows" :key="n.id">
        <NotificationItem
          :notification="n"
          :busy="!!store.busy[n.id]"
          compact
          @open="actions.open($event); emit('navigate')"
          @read="actions.read"
          @dismiss="actions.dismiss"
          @action="actions.act"
          @turn-off="(n, done) => actions.turnOff(n).then(done)"
          @undo-turn-off="(n, done) => actions.undoTurnOff(n).then(done)"
        />
      </li>
    </ul>
  </div>
</template>
