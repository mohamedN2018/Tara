<script setup lang="ts">
// One notification row. The root is an <article>, not a <button>: the whole row is
// a stretched link to the deep link, and the inline actions (accept, decline,
// follow back, join a group) and the "..." menu (mark read, remove, turn off
// notifications like this) are real buttons layered above it.
import { BellOff, Check, CheckCheck, MoreHorizontal, Trash2, UserPlus, UsersRound, X } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import {
  iconFor,
  inlineActions,
  isolateParts,
  notificationExcerpt,
  notificationText,
  urlFor,
  type InlineAction,
} from "@/components/notifications/kinds";
import { relativeTime } from "@/lib/format";
import { useEscapeKey } from "@/lib/useEscapeKey";
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
  /** "Turn off notifications like this"; resolves to whether it was saved. */
  turnOff: [notification: Notification, done: (ok: boolean) => void];
  undoTurnOff: [notification: Notification, done: (ok: boolean) => void];
}>();

const menuOpen = ref(false);
useEscapeKey(menuOpen, () => (menuOpen.value = false));
// Turned off from this row: a strip with Undo replaces the actions.
const turnedOff = ref(false);
function turnOff() {
  menuOpen.value = false;
  emit("turnOff", n.value, (ok) => (turnedOff.value = ok));
}
function undo() {
  emit("undoTurnOff", n.value, (ok) => (turnedOff.value = !ok));
}
function pick(fn: () => void) {
  menuOpen.value = false;
  fn();
}

const { t, te } = useI18n();
const directory = useDirectoryStore();

const n = computed(() => props.notification);
const icon = computed(() => iconFor(n.value.kind));
const unread = computed(() => !n.value.read_at);
// A Page's or Tara Support's reply has no person behind it (no actor_id).
const actorName = computed(() => {
  const kind = n.value.data?.sender_kind;
  if (kind === "support") return t("chatTeam.support");
  if (kind === "page") return String(n.value.data?.sender_name || t("chatTeam.pageFallback"));
  return directory.label(n.value.actor_id);
});
const text = computed(() => notificationText(n.value, t, te, actorName.value));
// The sentence keeps the UI's direction; the actor's name and the quoted
// message text are each isolated in a <bdi>, so an Arabic name or message in
// the English UI (or the reverse) neither flips the alignment nor drags the
// punctuation around.
const parts = computed(() => isolateParts(text.value, actorName.value, notificationExcerpt(n.value)));
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
  const r = n.value.resolution;
  if (!r) return "";
  // Group invitations have their own wording ("You joined the group").
  const own = `messenger.notif.resolutions.${r}`;
  if (n.value.kind === "group.invite" && te(own)) return t(own);
  const key = `notifications.resolutions.${r}`;
  return te(key) ? t(key) : "";
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
          class="absolute -bottom-1.5 -end-2 flex h-5 w-5 items-center justify-center rounded-full border-2 border-white bg-brand-600 text-white dark:border-gray-900"
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
      <p class="text-sm" :class="unread ? 'font-medium text-gray-900 dark:text-white' : 'text-gray-700 dark:text-gray-200'" data-testid="notification-text">
        <template v-for="(part, i) in parts" :key="i"><bdi v-if="part.isolate === 'name'" class="font-semibold">{{ part.text }}</bdi><bdi v-else-if="part.isolate === 'excerpt'" dir="auto" data-testid="notification-excerpt">{{ part.text }}</bdi><template v-else>{{ part.text }}</template></template>
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
        <button
          v-if="actions.includes('join')"
          type="button"
          class="btn-primary px-3 py-1.5 text-xs"
          :disabled="busy"
          data-testid="notification-join"
          @click="emit('action', n, 'join')"
        >
          <UsersRound class="h-3.5 w-3.5" /> {{ t("messenger.notif.joinGroup") }}
        </button>
        <button
          v-if="actions.includes('decline_invite')"
          type="button"
          class="btn-outline px-3 py-1.5 text-xs"
          :disabled="busy"
          data-testid="notification-decline-invite"
          @click="emit('action', n, 'decline_invite')"
        >
          <X class="h-3.5 w-3.5" /> {{ t("messenger.notif.declineInvite") }}
        </button>
      </div>
      <p
        v-else-if="resolutionText"
        class="mt-1 text-xs font-semibold"
        :class="n.resolution === 'accepted' || n.resolution === 'followed_back' ? 'text-green-600 dark:text-green-400' : 'text-gray-500 dark:text-gray-400'"
      >
        {{ resolutionText }}
      </p>
      <p v-if="turnedOff" class="pointer-events-auto relative z-10 mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-600 dark:text-gray-300" data-testid="notification-turned-off">
        <BellOff class="h-3.5 w-3.5" aria-hidden="true" /> {{ t("messenger.notif.turnedOff") }}
        <button type="button" class="font-semibold text-brand-600 hover:underline dark:text-brand-300" data-testid="notification-undo" @click="undo">
          {{ t("messenger.notif.undo") }}
        </button>
      </p>
    </div>

    <div class="relative z-10 flex shrink-0 items-center gap-0.5">
      <span v-if="unread" role="img" class="me-1 h-2 w-2 rounded-full bg-brand-500" :aria-label="t('notifications.unread')" />
      <div class="relative">
        <button
          type="button"
          class="flex h-8 w-8 items-center justify-center rounded-full border border-gray-200 bg-white text-gray-600 opacity-100 shadow-sm transition hover:bg-gray-100 focus-visible:opacity-100 sm:opacity-0 sm:group-hover:opacity-100 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300 dark:hover:bg-gray-800"
          :class="menuOpen ? '!opacity-100' : ''"
          :aria-label="t('messenger.notif.options')"
          :title="t('messenger.notif.options')"
          aria-haspopup="menu"
          :aria-expanded="menuOpen"
          data-testid="notification-menu"
          @click="menuOpen = !menuOpen"
        >
          <MoreHorizontal class="h-4 w-4" />
        </button>
        <template v-if="menuOpen">
          <div class="fixed inset-0 z-40" @click="menuOpen = false" />
          <div class="popover absolute end-0 z-50 mt-1 w-64 p-1" role="menu">
            <button
              v-if="unread"
              type="button"
              class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-start text-sm hover:bg-gray-100 dark:hover:bg-gray-800"
              role="menuitem"
              data-testid="notification-mark-read"
              @click="pick(() => emit('read', n.id))"
            >
              <CheckCheck class="h-4 w-4" aria-hidden="true" /> {{ t("messenger.notif.markRead") }}
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-start text-sm hover:bg-gray-100 dark:hover:bg-gray-800"
              role="menuitem"
              data-testid="notification-dismiss"
              @click="pick(() => emit('dismiss', n.id))"
            >
              <Trash2 class="h-4 w-4" aria-hidden="true" /> {{ t("messenger.notif.remove") }}
            </button>
            <button
              v-if="!turnedOff"
              type="button"
              class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-start text-sm hover:bg-gray-100 dark:hover:bg-gray-800"
              role="menuitem"
              data-testid="notification-turn-off"
              @click="turnOff"
            >
              <BellOff class="h-4 w-4" aria-hidden="true" /> {{ t("messenger.notif.turnOff") }}
            </button>
          </div>
        </template>
      </div>
    </div>
  </article>
</template>
