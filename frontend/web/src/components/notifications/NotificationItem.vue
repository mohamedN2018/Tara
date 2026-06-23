<script setup lang="ts">
import { Bell, Heart, MessageSquare, ShoppingBag, UserPlus } from "lucide-vue-next";
import { computed } from "vue";

import { relativeTime } from "@/lib/format";
import type { Notification } from "@/types";

const props = defineProps<{ notification: Notification }>();
defineEmits<{ read: [id: string] }>();

const icon = computed(() => {
  const map: Record<string, typeof Bell> = {
    reaction: Heart,
    comment: MessageSquare,
    friend_request: UserPlus,
    follow: UserPlus,
    listing: ShoppingBag,
  };
  return map[props.notification.kind] ?? Bell;
});
</script>

<template>
  <button
    class="flex w-full items-start gap-3 px-3 py-3 text-start transition hover:bg-gray-50 dark:hover:bg-gray-800/50"
    :class="!notification.read_at ? 'bg-brand-50/50 dark:bg-brand-950/30' : ''"
    @click="$emit('read', notification.id)"
  >
    <span class="mt-0.5 rounded-full bg-brand-100 p-1.5 text-brand-600 dark:bg-brand-900/50">
      <component :is="icon" class="h-4 w-4" />
    </span>
    <span class="min-w-0 flex-1">
      <span class="block text-sm">{{ notification.body }}</span>
      <time class="text-xs text-gray-400">{{ relativeTime(notification.created_at) }}</time>
    </span>
    <span v-if="!notification.read_at" class="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand-500" />
  </button>
</template>
