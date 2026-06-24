<script setup lang="ts">
import { Bell, Heart, MessageSquare, ShoppingBag, UserPlus } from "lucide-vue-next";
import { computed } from "vue";

import UserAvatar from "@/components/common/UserAvatar.vue";
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
    <span class="relative mt-0.5 shrink-0">
      <UserAvatar v-if="notification.actor_id" :name="notification.actor_id" :size="40" />
      <span v-else class="flex h-10 w-10 items-center justify-center rounded-full bg-brand-100 text-brand-600 dark:bg-brand-900/50">
        <component :is="icon" class="h-5 w-5" />
      </span>
      <span
        v-if="notification.actor_id"
        class="absolute -end-0.5 -bottom-0.5 flex h-5 w-5 items-center justify-center rounded-full border-2 border-white bg-brand-600 text-white dark:border-gray-900"
      >
        <component :is="icon" class="h-2.5 w-2.5" />
      </span>
    </span>
    <span class="min-w-0 flex-1">
      <span class="block text-sm">{{ notification.body }}</span>
      <time class="text-xs text-gray-400">{{ relativeTime(notification.created_at) }}</time>
    </span>
    <span v-if="!notification.read_at" class="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand-500" />
  </button>
</template>
