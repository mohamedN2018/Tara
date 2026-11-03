<script setup lang="ts">
import { BellOff } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { relativeTime } from "@/lib/format";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";
import type { Conversation } from "@/types";

const props = defineProps<{ conversations: Conversation[]; activeId?: string; selfId?: string }>();
defineEmits<{ select: [id: string] }>();

const { t } = useI18n();
const presence = usePresenceStore();
const directory = useDirectoryStore();

function isDm(c: Conversation): boolean {
  return c.type !== "group" && c.members.length <= 2;
}
function peerId(c: Conversation): string {
  return c.members.find((m) => m !== props.selfId) ?? c.members[0] ?? c.id;
}
function title(c: Conversation): string {
  if (c.title) return c.title;
  if (isDm(c)) return directory.label(peerId(c));
  const others = c.members.filter((m) => m !== props.selfId);
  return others.map((m) => directory.label(m)).join("، ") || t("messages.groupFallback");
}
</script>

<template>
  <ul class="divide-y divide-gray-100 dark:divide-gray-800">
    <li v-for="c in conversations" :key="c.id">
      <button
        class="flex w-full items-center gap-3 px-3 py-3 text-start transition hover:bg-gray-50 dark:hover:bg-gray-800/50"
        :class="activeId === c.id ? 'bg-brand-50 dark:bg-brand-950/40' : ''"
        @click="$emit('select', c.id)"
      >
        <span class="relative shrink-0">
          <UserAvatar :name="title(c)" :media-id="isDm(c) ? directory.avatarOf(peerId(c)) : null" />
          <span
            v-if="isDm(c) && presence.isOnline(peerId(c))"
            class="absolute -end-0.5 -bottom-0.5 h-3 w-3 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
            :title="t('presence.online')"
          />
        </span>
        <span class="min-w-0 flex-1">
          <span class="block truncate text-sm font-medium" dir="auto">{{ title(c) }}</span>
          <span class="block truncate text-xs text-gray-500 dark:text-gray-400">
            {{ isDm(c) ? (presence.isOnline(peerId(c)) ? t("presence.online") : t("messages.title")) : t("messages.membersCount", c.members.length) }}
          </span>
        </span>
        <BellOff v-if="c.muted_until" class="h-3.5 w-3.5 shrink-0 text-gray-500 dark:text-gray-400" :aria-label="t('messages.muted')" />
        <time v-if="c.last_message_at" class="shrink-0 text-[10px] text-gray-500 dark:text-gray-400">
          {{ relativeTime(c.last_message_at) }}
        </time>
      </button>
    </li>
  </ul>
</template>
