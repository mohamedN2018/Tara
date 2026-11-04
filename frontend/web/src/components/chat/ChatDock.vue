<script setup lang="ts">
// The dock at the bottom end of every page except the inbox (lg and up):
// expanded chat windows side by side, minimised chats as round heads, and the
// New message button (the pencil), which opens a window for the chosen chat.
import { PenSquare, X } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import ChatWindow from "@/components/chat/ChatWindow.vue";
import NewMessageModal from "@/components/chat/NewMessageModal.vue";
import { badgeText } from "@/lib/chat";
import { type DockWindow, useChatDockStore } from "@/stores/chatDock";
import { useChatUnreadStore } from "@/stores/chatUnread";
import { useDirectoryStore } from "@/stores/directory";
import type { Conversation } from "@/types";

const { t } = useI18n();
const route = useRoute();
const dock = useChatDockStore();
const chatUnread = useChatUnreadStore();
const directory = useDirectoryStore();

// Not on the inbox (it is the inbox), nor in the admin console, whose own
// corner it would cover.
const visible = computed(() => !route.path.startsWith("/messages") && !/^\/admin(\/|$)/.test(route.path));
const expanded = computed(() => dock.windows.filter((w) => !w.minimised));
const heads = computed(() => dock.windows.filter((w) => w.minimised));

function headName(w: DockWindow): string {
  return w.peerId ? directory.label(w.peerId) : w.title || t("nav.messages");
}

function onCreated(conversation: Conversation) {
  dock.composing = false;
  dock.open(conversation.id);
}
</script>

<template>
  <div v-if="visible" class="pointer-events-none fixed bottom-0 end-4 z-30 hidden items-end gap-3 lg:flex" :aria-label="t('messenger.dock.region')" role="region" data-testid="chat-dock">
    <div class="pointer-events-auto flex items-end gap-3">
      <ChatWindow v-for="w in expanded" :key="w.id" :conversation-id="w.id" />
    </div>

    <!-- Heads and the New message button -->
    <div class="pointer-events-auto mb-6 flex flex-col items-center gap-3">
      <div v-for="w in heads" :key="w.id" class="group relative">
        <button
          type="button"
          class="rounded-full shadow-pop ring-2 ring-white dark:ring-gray-900"
          :aria-label="t('messenger.dock.expand', { name: headName(w) })"
          data-testid="chat-head"
          @click="dock.open(w.id)"
        >
          <UserAvatar :name="headName(w)" :media-id="w.peerId ? directory.avatarOf(w.peerId) : null" :size="48" />
        </button>
        <button
          type="button"
          class="absolute -end-1 -top-1 hidden h-5 w-5 items-center justify-center rounded-full bg-white text-gray-600 shadow group-focus-within:flex group-hover:flex dark:bg-gray-800 dark:text-gray-200"
          :aria-label="t('messenger.dock.close')"
          @click="dock.close(w.id)"
        >
          <X class="h-3 w-3" />
        </button>
      </div>
      <button
        type="button"
        class="relative flex h-14 w-14 items-center justify-center rounded-full border border-gray-200 bg-white text-gray-800 shadow-pop transition hover:text-brand-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-100 dark:hover:text-brand-300"
        :aria-label="t('messenger.newMessage')"
        :title="t('messenger.newMessage')"
        data-testid="messenger-fab"
        @click="dock.composing = true"
      >
        <PenSquare class="h-6 w-6" aria-hidden="true" />
        <span v-if="chatUnread.conversations > 0" class="badge absolute -end-1 -top-1">{{ badgeText(chatUnread.conversations) }}</span>
      </button>
    </div>
  </div>
  <NewMessageModal v-if="dock.composing" @close="dock.composing = false" @done="onCreated" />
</template>
