<script setup lang="ts">
import { Bell, Heart, MessageSquare, ShoppingBag, UserPlus } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { relativeTime } from "@/lib/format";
import { useDirectoryStore } from "@/stores/directory";
import type { Notification } from "@/types";

const props = defineProps<{ notification: Notification }>();
defineEmits<{ read: [id: string] }>();

const { t, te } = useI18n();
const directory = useDirectoryStore();

const icon = computed(() => {
  const map: Record<string, typeof Bell> = {
    "post.reaction": Heart,
    "post.comment": MessageSquare,
    "comment.reply": MessageSquare,
    "friend.request": UserPlus,
    "friend.accepted": UserPlus,
    follow: UserPlus,
    message: MessageSquare,
    "listing.status": ShoppingBag,
  };
  return map[props.notification.kind] ?? Bell;
});

const actorName = computed(() => directory.label(props.notification.actor_id));

// The stored `body` is a fixed English sentence (or a message preview), so the
// text is rebuilt from the kind; unknown kinds show the body as it came.
const text = computed(() => {
  const { kind, body } = props.notification;
  const key = `notifications.kinds.${kind.replace(".", "_")}`;
  if (!te(key)) return body;
  if (kind === "listing.status") {
    const status = body.split(" ").pop() ?? "";
    const statusKey = `market.statuses.${status}`;
    return t(key, { status: te(statusKey) ? t(statusKey) : status });
  }
  return t(key, { name: actorName.value, body });
});
</script>

<template>
  <button
    class="flex w-full items-start gap-3 px-3 py-3 text-start transition hover:bg-gray-50 dark:hover:bg-gray-800/50"
    :class="!notification.read_at ? 'bg-brand-50/50 dark:bg-brand-950/30' : ''"
    @click="$emit('read', notification.id)"
  >
    <span class="relative mt-0.5 shrink-0">
      <UserAvatar v-if="notification.actor_id" :name="actorName" :media-id="directory.avatarOf(notification.actor_id)" :size="40" />
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
      <span class="block text-sm" dir="auto">{{ text }}</span>
      <time class="text-xs text-gray-400">{{ relativeTime(notification.created_at) }}</time>
    </span>
    <span v-if="!notification.read_at" class="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand-500" />
  </button>
</template>
