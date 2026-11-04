<script setup lang="ts">
// The inbox's third column (a drawer below lg): who this chat is with, then
// collapsible sections like the reference layout: Chat info (pinned messages),
// Customise chat (mute), Chat members (groups), Media and files, Search in
// conversation, and Privacy and support (archive, clear, block, report, leave).
import { Archive, Ban, Bell, BellOff, ChevronDown, Flag, LogOut, Pin, Search, Trash2, User, Users, X } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import ChatSearch from "@/components/chat/ChatSearch.vue";
import SharedMediaPanel from "@/components/chat/SharedMediaPanel.vue";
import ListingStrip from "@/components/chat/ListingStrip.vue";
import { typePreview } from "@/lib/chat";
import { relativeTime } from "@/lib/format";
import { usePresenceStore } from "@/stores/presence";
import { useDirectoryStore } from "@/stores/directory";
import type { Conversation, Message } from "@/types";

const props = defineProps<{ conversation: Conversation; selfId: string; title: string; nameOf: (id: string) => string }>();
const emit = defineEmits<{
  close: [];
  jump: [messageId: string];
  openResult: [message: Message];
  mute: [minutes: number];
  archive: [];
  clear: [];
  block: [];
  report: [];
  manageGroup: [];
}>();

const { t } = useI18n();
const directory = useDirectoryStore();
const presence = usePresenceStore();

const isGroup = computed(() => props.conversation.type === "group");
const peerId = computed(() =>
  isGroup.value ? "" : (props.conversation.members.find((m) => m !== props.selfId) ?? ""),
);
const pending = computed(() => !props.conversation.title && !!peerId.value && directory.pending(peerId.value));
const canBlock = computed(() => props.conversation.type === "dm" && !!peerId.value);
const MUTE_OPTIONS = [
  { minutes: 60, label: "messages.muteHour" },
  { minutes: 480, label: "messages.muteEightHours" },
  { minutes: 10080, label: "messages.muteWeek" },
];
const ROW = "flex w-full items-center gap-3 rounded-lg px-2 py-2 text-start text-sm font-medium hover:bg-gray-100 dark:hover:bg-gray-800";
const SUMMARY =
  "flex cursor-pointer list-none items-center justify-between rounded-lg px-2 py-2 text-sm font-semibold hover:bg-gray-100 dark:hover:bg-gray-800 [&::-webkit-details-marker]:hidden";
</script>

<template>
  <aside class="flex h-full min-h-0 flex-col bg-white dark:bg-gray-900" :aria-label="t('messenger.info.open')" data-testid="conversation-info">
    <div class="flex items-center justify-end px-2 pt-2">
      <button class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('messenger.info.close')" @click="emit('close')">
        <X class="h-4 w-4" />
      </button>
    </div>
    <div class="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
      <!-- Who -->
      <div class="flex flex-col items-center gap-2 pb-3 text-center">
        <UserAvatar :name="title" :media-id="peerId ? directory.avatarOf(peerId) : null" :size="72" />
        <p v-if="pending" class="h-5 w-40 animate-pulse rounded bg-gray-200 dark:bg-gray-700" data-testid="info-title-skeleton" />
        <p v-else class="text-base font-bold" dir="auto">{{ title }}</p>
        <p v-if="peerId && presence.isOnline(peerId)" class="text-xs text-green-600 dark:text-green-400">{{ t("presence.online") }}</p>
        <p v-else-if="isGroup" class="text-xs text-gray-500 dark:text-gray-400">{{ t("messages.membersCount", conversation.members.length) }}</p>
        <div class="flex gap-3">
          <RouterLink
            v-if="peerId"
            :to="{ name: 'profile-by-id', params: { id: peerId } }"
            class="flex flex-col items-center gap-1 text-xs"
            data-testid="info-profile"
          >
            <span class="flex h-9 w-9 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800"><User class="h-4 w-4" /></span>
            {{ t("messenger.info.viewProfile") }}
          </RouterLink>
        </div>
      </div>

      <ListingStrip v-if="conversation.type === 'marketplace' && conversation.listing_id" class="mb-2 rounded-xl" :listing-id="conversation.listing_id" />

      <details class="group/s" open>
        <summary :class="SUMMARY">{{ t("messenger.info.chatInfo") }} <ChevronDown class="h-4 w-4 transition group-open/s:rotate-180" aria-hidden="true" /></summary>
        <div class="pb-2">
          <p class="px-2 pb-1 text-xs font-semibold text-gray-500 dark:text-gray-400">{{ t("messenger.info.pinned") }}</p>
          <p v-if="!conversation.pinned_messages.length" class="px-2 text-xs text-gray-500 dark:text-gray-400">{{ t("messenger.info.noPinned") }}</p>
          <button v-for="pin in conversation.pinned_messages" :key="pin.id" :class="ROW" @click="emit('jump', pin.id)">
            <Pin class="h-4 w-4 shrink-0 text-brand-500" aria-hidden="true" />
            <span class="min-w-0 flex-1 truncate" dir="auto"><b>{{ nameOf(pin.sender_id) }}:</b> {{ pin.body || typePreview(pin.type, t) }}</span>
          </button>
        </div>
      </details>

      <details class="group/s">
        <summary :class="SUMMARY">{{ t("messenger.info.customise") }} <ChevronDown class="h-4 w-4 transition group-open/s:rotate-180" aria-hidden="true" /></summary>
        <div class="pb-2">
          <button v-if="conversation.muted_until" :class="ROW" @click="emit('mute', 0)">
            <BellOff class="h-4 w-4" aria-hidden="true" />
            <span class="flex-1">{{ t("messages.unmute") }}</span>
            <span class="text-xs text-gray-500">{{ relativeTime(conversation.muted_until) }}</span>
          </button>
          <template v-else>
            <p class="px-2 pb-1 text-xs font-semibold text-gray-500 dark:text-gray-400">{{ t("messenger.muteFor") }}</p>
            <button v-for="o in MUTE_OPTIONS" :key="o.minutes" :class="ROW" :data-testid="`info-mute-${o.minutes}`" @click="emit('mute', o.minutes)">
              <Bell class="h-4 w-4" aria-hidden="true" /> {{ t(o.label) }}
            </button>
          </template>
        </div>
      </details>

      <details v-if="isGroup" class="group/s">
        <summary :class="SUMMARY">{{ t("messenger.info.members") }} <ChevronDown class="h-4 w-4 transition group-open/s:rotate-180" aria-hidden="true" /></summary>
        <ul class="pb-1">
          <li v-for="m in conversation.member_states" :key="m.account_id" class="flex items-center gap-2 px-2 py-1.5">
            <UserAvatar :name="directory.label(m.account_id)" :media-id="directory.avatarOf(m.account_id)" :size="28" />
            <span class="min-w-0 flex-1 truncate text-sm" dir="auto">{{ m.account_id === selfId ? t("messages.you") : directory.label(m.account_id) }}</span>
            <span v-if="m.role === 'admin'" class="text-xs text-amber-600">{{ t("messages.admin") }}</span>
          </li>
        </ul>
        <button :class="ROW" data-testid="info-manage-group" @click="emit('manageGroup')">
          <Users class="h-4 w-4" aria-hidden="true" /> {{ t("messages.groupInfo") }}
        </button>
      </details>

      <details class="group/s">
        <summary :class="SUMMARY" data-testid="info-media">{{ t("messenger.info.media") }} <ChevronDown class="h-4 w-4 transition group-open/s:rotate-180" aria-hidden="true" /></summary>
        <div class="h-80 pb-2">
          <SharedMediaPanel :key="conversation.id" class="h-full" :conversation-id="conversation.id" @jump="emit('jump', $event)" />
        </div>
      </details>

      <details class="group/s">
        <summary :class="SUMMARY" data-testid="info-search">
          <span class="flex items-center gap-2"><Search class="h-4 w-4" aria-hidden="true" />{{ t("messenger.info.search") }}</span>
          <ChevronDown class="h-4 w-4 transition group-open/s:rotate-180" aria-hidden="true" />
        </summary>
        <div class="h-72 pb-2">
          <ChatSearch class="h-full" :conversation-id="conversation.id" :name-of="nameOf" @open="emit('openResult', $event)" />
        </div>
      </details>

      <details class="group/s" open>
        <summary :class="SUMMARY">{{ t("messenger.info.privacy") }} <ChevronDown class="h-4 w-4 transition group-open/s:rotate-180" aria-hidden="true" /></summary>
        <div class="pb-2">
          <button :class="ROW" data-testid="info-archive" @click="emit('archive')">
            <Archive class="h-4 w-4" aria-hidden="true" /> {{ conversation.archived ? t("messages.unarchive") : t("messages.archive") }}
          </button>
          <button :class="ROW" @click="emit('clear')">
            <Trash2 class="h-4 w-4" aria-hidden="true" /> {{ t("messages.clearChat") }}
          </button>
          <template v-if="canBlock">
            <button :class="ROW" data-testid="info-block" @click="emit('block')">
              <Ban class="h-4 w-4" aria-hidden="true" /> {{ pending ? t("messenger.blockNoName") : t("messenger.block", { name: title }) }}
            </button>
            <button :class="[ROW, 'text-red-600']" data-testid="info-report" @click="emit('report')">
              <Flag class="h-4 w-4" aria-hidden="true" /> {{ pending ? t("messenger.reportNoName") : t("messenger.report", { name: title }) }}
            </button>
          </template>
          <button v-if="isGroup" :class="[ROW, 'text-red-600']" @click="emit('manageGroup')">
            <LogOut class="h-4 w-4" aria-hidden="true" /> {{ t("messages.leaveGroup") }}
          </button>
        </div>
      </details>
    </div>
  </aside>
</template>
