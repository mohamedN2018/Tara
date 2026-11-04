<script setup lang="ts">
// The inbox column: each row shows the last message ("You: ..."), the time, an
// unread badge, and on hover or focus a "..." menu with the actions for that
// chat (mute for a while, archive, clear, block or report the other person).
import { BellOff, ChevronDown, MoreHorizontal, Store } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { badgeText, conversationTitle, isTeamThread, teamThreadTitle } from "@/lib/chat";
import { relativeTime } from "@/lib/format";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";
import type { Conversation } from "@/types";

import ListingAvatar from "./ListingAvatar.vue";
import MessagePreview from "./MessagePreview.vue";

export type RowAction = "mute" | "unmute" | "archive" | "unarchive" | "clear" | "block" | "report" | "accept" | "decline";

const props = defineProps<{ conversations: Conversation[]; activeId?: string; selfId?: string }>();
const emit = defineEmits<{ select: [id: string]; action: [id: string, action: RowAction, minutes?: number] }>();

const { t, locale } = useI18n();
const presence = usePresenceStore();
const directory = useDirectoryStore();

const MUTE_OPTIONS = [
  { minutes: 60, label: "messages.muteHour" },
  { minutes: 480, label: "messages.muteEightHours" },
  { minutes: 10080, label: "messages.muteWeek" },
];
const ROW = "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm hover:bg-gray-100 dark:hover:bg-gray-800";

const menuFor = ref("");
const muteOpen = ref(false);
const menuOpen = ref(false);
useEscapeKey(menuOpen, closeMenu);

function openMenu(id: string) {
  menuFor.value = menuFor.value === id ? "" : id;
  menuOpen.value = !!menuFor.value;
  muteOpen.value = false;
}
function closeMenu() {
  menuFor.value = "";
  menuOpen.value = false;
  muteOpen.value = false;
}
function act(c: Conversation, action: RowAction, minutes?: number) {
  closeMenu();
  emit("action", c.id, action, minutes);
}

function isDm(c: Conversation): boolean {
  return c.type !== "group" && !isTeamThread(c) && c.members.length <= 2;
}
function peerId(c: Conversation): string {
  return c.members.find((m) => m !== props.selfId) ?? c.members[0] ?? c.id;
}
function title(c: Conversation): string {
  if (isTeamThread(c)) return teamThreadTitle(c, t);
  if (c.title) return c.title;
  if (isDm(c)) return directory.label(peerId(c));
  return conversationTitle(c, props.selfId, directory.label, locale.value, t("messages.groupFallback"));
}
/** The second line when there is no message to preview. */
function subtitle(c: Conversation): string {
  if (isTeamThread(c)) return "";
  if (!isDm(c)) return t("messages.membersCount", c.members.length);
  return presence.isOnline(peerId(c)) ? t("presence.online") : "";
}
function isRequest(c: Conversation): boolean {
  return c.request_status === "pending" || c.request_status === "spam";
}
</script>

<template>
  <ul class="space-y-0.5 px-1.5 py-1">
    <li v-for="c in conversations" :key="c.id" class="group relative" data-testid="conversation-row">
      <button
        class="flex w-full items-center gap-3 rounded-xl px-2 py-2 pe-10 text-start transition hover:bg-gray-100 dark:hover:bg-gray-800/70"
        :class="activeId === c.id ? 'bg-brand-50 dark:bg-brand-950/40' : ''"
        :aria-current="activeId === c.id ? 'true' : undefined"
        @click="$emit('select', c.id)"
      >
        <span class="relative shrink-0">
          <ListingAvatar
            v-if="c.type === 'marketplace' && c.listing_title"
            :cover-media-id="c.listing_cover_media_id"
            :name="title(c)"
            :peer-media-id="directory.avatarOf(peerId(c))"
          />
          <UserAvatar v-else :name="title(c)" :media-id="isDm(c) ? directory.avatarOf(peerId(c)) : null" :size="48" />
          <span
            v-if="isDm(c) && !isRequest(c) && presence.isOnline(peerId(c)) && !(c.type === 'marketplace' && c.listing_title)"
            class="absolute -end-0.5 -bottom-0.5 h-3.5 w-3.5 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
            :title="t('presence.online')"
          />
        </span>
        <span class="min-w-0 flex-1">
          <span class="flex min-w-0 items-center gap-1">
            <span class="truncate text-sm" :class="[c.unread_count ? 'font-bold' : 'font-medium', c.type === 'marketplace' && c.listing_title ? 'max-w-[55%] shrink-0' : '']" dir="auto">{{ title(c) }}</span>
            <template v-if="c.type === 'marketplace' && c.listing_title">
              <span class="shrink-0 text-sm text-gray-500 dark:text-gray-400" aria-hidden="true">·</span>
              <span class="min-w-0 truncate text-sm text-accent-700 dark:text-accent-300" dir="auto" data-testid="conversation-listing">{{ c.listing_title }}</span>
            </template>
            <Store v-else-if="c.type === 'marketplace'" class="h-3.5 w-3.5 shrink-0 text-accent-600 dark:text-accent-300" :aria-label="t('messenger.marketplaceBadge')" />
          </span>
          <span class="flex items-center gap-1 text-xs" :class="c.unread_count ? 'font-semibold text-gray-900 dark:text-white' : 'text-gray-500 dark:text-gray-400'">
            <MessagePreview :conversation="c" :self-id="selfId" :fallback="subtitle(c)" />
            <template v-if="c.last_message_at">
              <span aria-hidden="true">·</span>
              <time class="shrink-0">{{ relativeTime(c.last_message_at) }}</time>
            </template>
          </span>
        </span>
        <BellOff v-if="c.muted_until" class="h-3.5 w-3.5 shrink-0 text-gray-500 dark:text-gray-400" :aria-label="t('messages.muted')" />
        <span
          v-if="c.unread_count"
          class="badge shrink-0"
          :class="c.muted_until ? 'opacity-60' : ''"
          :aria-label="t('messages.unreadCount', c.unread_count)"
          data-testid="conversation-unread"
        >
          {{ badgeText(c.unread_count) }}
        </span>
      </button>

      <!-- Row menu: shown on hover, on keyboard focus, and while open -->
      <button
        type="button"
        class="absolute end-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border border-gray-200 bg-white text-gray-600 opacity-0 shadow-sm transition focus:opacity-100 group-hover:opacity-100 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300"
        :class="menuFor === c.id ? '!opacity-100' : ''"
        :aria-label="t('messenger.rowActions', { name: title(c) })"
        aria-haspopup="menu"
        :aria-expanded="menuFor === c.id"
        data-testid="conversation-row-menu"
        @click.stop="openMenu(c.id)"
      >
        <MoreHorizontal class="h-4 w-4" />
      </button>
      <template v-if="menuFor === c.id">
        <div class="fixed inset-0 z-40" @click="closeMenu" />
        <div class="popover absolute end-2 top-full z-50 -mt-1 w-60 p-1" role="menu" data-testid="conversation-row-actions">
          <template v-if="isRequest(c)">
            <button :class="ROW" role="menuitem" @click="act(c, 'accept')">{{ t("messenger.request.accept") }}</button>
            <button v-if="c.request_status === 'pending'" :class="ROW" role="menuitem" @click="act(c, 'decline')">{{ t("messenger.request.decline") }}</button>
          </template>
          <template v-else>
            <button v-if="c.muted_until" :class="ROW" role="menuitem" @click="act(c, 'unmute')">{{ t("messages.unmute") }}</button>
            <template v-else>
              <button :class="ROW" role="menuitem" :aria-expanded="muteOpen" @click="muteOpen = !muteOpen">
                <span class="flex-1">{{ t("messenger.muteFor") }}</span>
                <ChevronDown class="h-4 w-4 transition" :class="muteOpen ? 'rotate-180' : ''" aria-hidden="true" />
              </button>
              <div v-if="muteOpen" class="ms-3 border-s border-gray-200 ps-1 dark:border-gray-700">
                <button v-for="o in MUTE_OPTIONS" :key="o.minutes" :class="ROW" role="menuitem" @click="act(c, 'mute', o.minutes)">
                  {{ t(o.label) }}
                </button>
              </div>
            </template>
            <button :class="ROW" role="menuitem" @click="act(c, c.archived ? 'unarchive' : 'archive')">
              {{ c.archived ? t("messages.unarchive") : t("messages.archive") }}
            </button>
            <button :class="ROW" role="menuitem" @click="act(c, 'clear')">{{ t("messages.clearChat") }}</button>
          </template>
          <template v-if="isDm(c) && c.type === 'dm'">
            <div class="my-1 border-t border-gray-100 dark:border-gray-800" />
            <button :class="ROW" role="menuitem" data-testid="row-block" @click="act(c, 'block')">{{ t("messenger.block", { name: title(c) }) }}</button>
            <button :class="[ROW, 'text-red-600']" role="menuitem" data-testid="row-report" @click="act(c, 'report')">
              {{ t("messenger.report", { name: title(c) }) }}
            </button>
          </template>
        </div>
      </template>
    </li>
  </ul>
</template>
