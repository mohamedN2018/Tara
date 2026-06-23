<script setup lang="ts">
import { relativeTime } from "@/lib/format";
import type { Conversation } from "@/types";

import UserAvatar from "@/components/common/UserAvatar.vue";

defineProps<{ conversations: Conversation[]; activeId?: string }>();
defineEmits<{ select: [id: string] }>();
</script>

<template>
  <ul class="divide-y divide-gray-100 dark:divide-gray-800">
    <li v-for="c in conversations" :key="c.id">
      <button
        class="flex w-full items-center gap-3 px-3 py-3 text-start transition hover:bg-gray-50 dark:hover:bg-gray-800/50"
        :class="activeId === c.id ? 'bg-brand-50 dark:bg-brand-950/40' : ''"
        @click="$emit('select', c.id)"
      >
        <UserAvatar :name="c.title || c.id" />
        <span class="min-w-0 flex-1">
          <span class="block truncate text-sm font-medium">{{ c.title || c.id.slice(0, 8) }}</span>
          <span class="block truncate text-xs text-gray-500">{{ c.members.length }} members</span>
        </span>
        <time v-if="c.last_message_at" class="shrink-0 text-[10px] text-gray-400">
          {{ relativeTime(c.last_message_at) }}
        </time>
      </button>
    </li>
  </ul>
</template>
