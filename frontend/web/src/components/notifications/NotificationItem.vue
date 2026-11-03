<script setup lang="ts">
// One notification row. The root is an <article>, not a <button>: the whole row is
// a stretched link to the deep link, and the inline actions (accept, decline,
// follow back, mark read, dismiss) are real buttons layered above it.
import { Check, CheckCheck, UserPlus, X } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { iconFor, inlineActions, notificationText, urlFor, type InlineAction } from "@/components/notifications/kinds";
import { relativeTime } from "@/lib/format";
import { useDirectoryStore } from "@/stores/directory";
import type { Notification } from "@/types";

const props = withDefaults(defineProps<{ notification: Notification; busy?: boolean; compact?: boolean }>(), {
  busy: false,
  compact: false,
});
const emit = defineEmits<{
  open: [notification: Notification];
  read: [id: string];
  dismiss: [id: string];
  action: [notification: Notification, action: InlineAction];
}>();

const { t, te } = useI18n();
const directory = useDirectoryStore();

const n = computed(() => props.notification);
const icon = computed(() => iconFor(n.value.kind));
const unread = computed(() => !n.value.read_at);
const actorName = computed(() => directory.label(n.value.actor_id));
const text = computed(() => notificationText(n.value, t, te, actorName.value));
const url = computed(() => urlFor(n.value));
const actions = computed(() => inlineActions(n.value));
// Up to two faces for a group ("X and 3 others"), newest first.
const faces = computed(() => {
  const ids = (n.value.recent_actor_ids?.length ? n.value.recent_actor_ids : [n.value.actor_id]).filter(
    (id): id is string => !!id,
  );
  return ids.slice(0, 2);
});
const resolutionText = computed(() => {
  const key = `notifications.resolutions.${n.value.resolution}`;
  return n.value.resolution && te(key) ? t(key) : "";
});
</script>

<template>
  <article
    class="group relative flex items-start gap-3 px-3 py-3 transition hover:bg-gray-50 dark:hover:bg-gray-800/50"
    :class="unread ? 'bg-brand-50/60 dark:bg-brand-950/30' : ''"
    :data-kind="n.kind"
    data-testid="notification-item"
  >
    <RouterLink
      :to="url"
      class="absolute inset-0 z-0 rounded-[inherit] focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400"
      :aria-label="text"
      @click="emit('open', n)"
    />

    <span class="pointer-events-none relative mt-0.5 shrink-0">
      <template v-if="faces.length">
        <span class="relative block" :class="faces.length > 1 ? 'h-10 w-11' : 'h-10 w-10'">
          <UserAvatar
            v-if="faces[1]"
            class="absolute end-0 top-0 ring-2 ring-white dark:ring-gray-900"
            :name="directory.label(faces[1])"
            :media-id="directory.avatarOf(faces[1])"
            :size="28"
          />
          <UserAvatar
            :class="faces[1] ? 'absolute bottom-0 start-0 ring-2 ring-white dark:ring-gray-900' : ''"
            :name="directory.label(faces[0])"
            :media-id="directory.avatarOf(faces[0])"
            :size="faces[1] ? 30 : 40"
          />
        </span>
        <span
          class="absolute -bottom-0.5 -end-0.5 flex h-5 w-5 items-center justify-center rounded-full border-2 border-white bg-brand-600 text-white dark:border-gray-900"
        >
          <component :is="icon" class="h-2.5 w-2.5" />
        </span>
      </template>
      <span
        v-else
        class="flex h-10 w-10 items-center justify-center rounded-full bg-brand-100 text-brand-600 dark:bg-brand-900/50 dark:text-brand-300"
      >
        <component :is="icon" class="h-5 w-5" />
      </span>
    </span>

    <div class="pointer-events-none relative min-w-0 flex-1">
      <p class="text-sm" :class="unread ? 'font-medium text-gray-900 dark:text-white' : 'text-gray-700 dark:text-gray-200'" dir="auto">
        {{ text }}
      </p>
      <time class="text-xs text-gray-500 dark:text-gray-400" :datetime="n.last_event_at ?? n.created_at">
        {{ relativeTime(n.last_event_at ?? n.created_at) }}
      </time>

      <div v-if="actions.length" class="pointer-events-auto relative z-10 mt-2 flex flex-wrap gap-2">
        <button
          v-if="actions.includes('accept')"
          type="button"
          class="btn-primary px-3 py-1.5 text-xs"
          :disabled="busy"
          data-testid="notification-accept"
          @click="emit('action', n, 'accept')"
        >
          <Check class="h-3.5 w-3.5" /> {{ t("notifications.actions.accept") }}
        </button>
        <button
          v-if="actions.includes('decline')"
          type="button"
          class="btn-outline px-3 py-1.5 text-xs"
          :disabled="busy"
          data-testid="notification-decline"
          @click="emit('action', n, 'decline')"
        >
          <X class="h-3.5 w-3.5" /> {{ t("notifications.actions.decline") }}
        </button>
        <button
          v-if="actions.includes('follow_back')"
          type="button"
          class="btn-soft px-3 py-1.5 text-xs"
          :disabled="busy"
          data-testid="notification-follow-back"
          @click="emit('action', n, 'follow_back')"
        >
          <UserPlus class="h-3.5 w-3.5" /> {{ t("notifications.actions.followBack") }}
        </button>
      </div>
      <p
        v-else-if="resolutionText"
        class="mt-1 text-xs font-semibold"
        :class="n.resolution === 'accepted' || n.resolution === 'followed_back' ? 'text-green-600 dark:text-green-400' : 'text-gray-500 dark:text-gray-400'"
      >
        {{ resolutionText }}
      </p>
    </div>

    <div class="relative z-10 flex shrink-0 items-center gap-0.5">
      <span v-if="unread" role="img" class="me-1 h-2 w-2 rounded-full bg-brand-500" :aria-label="t('notifications.unread')" />
      <button
        v-if="unread"
        type="button"
        class="rounded-full p-1.5 text-gray-400 opacity-100 transition hover:bg-gray-200 hover:text-gray-700 focus-visible:opacity-100 sm:opacity-0 sm:group-hover:opacity-100 dark:hover:bg-gray-700 dark:hover:text-gray-100"
        :title="t('notifications.actions.markRead')"
        :aria-label="t('notifications.actions.markRead')"
        data-testid="notification-mark-read"
        @click="emit('read', n.id)"
      >
        <CheckCheck class="h-4 w-4" />
      </button>
      <button
        v-if="!compact"
        type="button"
        class="rounded-full p-1.5 text-gray-400 opacity-100 transition hover:bg-gray-200 hover:text-gray-700 focus-visible:opacity-100 sm:opacity-0 sm:group-hover:opacity-100 dark:hover:bg-gray-700 dark:hover:text-gray-100"
        :title="t('notifications.actions.dismiss')"
        :aria-label="t('notifications.actions.dismiss')"
        data-testid="notification-dismiss"
        @click="emit('dismiss', n.id)"
      >
        <X class="h-4 w-4" />
      </button>
    </div>
  </article>
</template>
