<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { relativeTime } from "@/lib/format";
import { chatService } from "@/services/chat";
import type { Conversation } from "@/types";

const props = withDefaults(defineProps<{ limit?: number }>(), { limit: 8 });
const emit = defineEmits<{ navigate: [] }>();

const { t } = useI18n();
const items = ref<Conversation[]>([]);
const loading = ref(true);
const error = ref(false);

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const convos = await chatService.conversations();
    items.value = convos.slice(0, props.limit);
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="min-h-24">
    <LoadingSkeleton v-if="loading" :rows="3" />
    <ErrorState v-else-if="error" @retry="load" />
    <EmptyState v-else-if="items.length === 0">{{ t("messages.noConversations") }}</EmptyState>
    <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800">
      <li v-for="c in items" :key="c.id">
        <RouterLink
          :to="`/messages/${c.id}`"
          class="flex items-center gap-3 px-2 py-2 transition hover:bg-gray-100 dark:hover:bg-gray-800"
          @click="emit('navigate')"
        >
          <UserAvatar :name="c.title || c.id" :size="40" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm font-medium">{{ c.title || c.id.slice(0, 8) }}</span>
            <span class="block truncate text-xs text-gray-500">
              {{ c.members.length }} {{ t("messages.title") }}
            </span>
          </span>
          <time v-if="c.last_message_at" class="shrink-0 text-[10px] text-gray-400">
            {{ relativeTime(c.last_message_at) }}
          </time>
        </RouterLink>
      </li>
    </ul>
  </div>
</template>
