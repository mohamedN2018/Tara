<script setup lang="ts">
// The top bar's Messenger button. From `sm` up it opens a dropdown: title,
// an options menu (Message requests, Archived chats, Marketplace), New message,
// a search field that opens the inbox's message search, All / Unread chips and
// the paged chat list, with "See all in Messenger" at the bottom. Phones get a
// plain link to the inbox with the same unread badge.
import { Archive, Inbox, MessageCircle, MoreHorizontal, PenSquare, Search, ShieldAlert, Store } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import MessagesPanel from "@/components/chat/MessagesPanel.vue";
import NewMessageModal from "@/components/chat/NewMessageModal.vue";
import { badgeText } from "@/lib/chat";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useChatUnreadStore } from "@/stores/chatUnread";
import type { Conversation } from "@/types";

const { t } = useI18n();
const router = useRouter();
const chatUnread = useChatUnreadStore();

const open = ref(false);
const optionsOpen = ref(false);
const composing = ref(false);
const unreadOnly = ref(false);
const query = ref("");
useEscapeKey(open, () => {
  if (optionsOpen.value) optionsOpen.value = false;
  else open.value = false;
});

function close() {
  open.value = false;
  optionsOpen.value = false;
}

function toggle() {
  open.value = !open.value;
  optionsOpen.value = false;
  if (open.value) void chatUnread.refresh();
}

function search() {
  const q = query.value.trim();
  close();
  void router.push({ path: "/messages", query: { search: "1", ...(q ? { q } : {}) } });
}

function startNew() {
  close();
  composing.value = true;
}

function onCreated(conversation: Conversation) {
  composing.value = false;
  void router.push(`/messages/${conversation.id}`);
}

const FOLDER_LINKS = [
  { folder: "requests", icon: Inbox, label: "messenger.folders.requests" },
  { folder: "archived", icon: Archive, label: "messenger.folders.archived" },
  { folder: "marketplace", icon: Store, label: "messenger.folders.marketplace" },
  { folder: "spam", icon: ShieldAlert, label: "messenger.folders.spam" },
] as const;
</script>

<template>
  <!-- Phones: straight to the inbox -->
  <RouterLink
    to="/messages"
    class="icon-btn relative shrink-0 sm:hidden"
    :aria-label="chatUnread.conversations > 0 ? t('messages.unreadBadge', chatUnread.conversations) : t('nav.messages')"
    :title="t('nav.messages')"
    data-testid="messenger-mobile"
  >
    <MessageCircle class="h-5 w-5" />
    <span v-if="chatUnread.conversations > 0" class="badge absolute -end-1 -top-1 !bg-accent-700 ring-2 ring-white dark:ring-gray-950">
      {{ badgeText(chatUnread.conversations) }}
    </span>
  </RouterLink>

  <div class="relative hidden shrink-0 sm:block">
    <button
      class="icon-btn relative"
      :class="open ? '!bg-brand-50 !text-brand-700 dark:!bg-brand-950/70 dark:!text-brand-300' : ''"
      :aria-label="chatUnread.conversations > 0 ? t('messages.unreadBadge', chatUnread.conversations) : t('nav.messages')"
      :title="t('nav.messages')"
      aria-haspopup="dialog"
      :aria-expanded="open"
      data-testid="messenger-button"
      @click="toggle"
    >
      <MessageCircle class="h-5 w-5" />
      <span v-if="chatUnread.conversations > 0" class="badge absolute -end-1 -top-1 !bg-accent-700 ring-2 ring-white dark:ring-gray-950" data-testid="messages-badge">
        {{ badgeText(chatUnread.conversations) }}
      </span>
    </button>
    <template v-if="open">
      <div class="fixed inset-0 z-40" @click="close" />
      <div
        class="popover absolute end-0 z-50 mt-2 flex max-h-[calc(100vh-5rem)] w-[22.5rem] max-w-[92vw] flex-col p-2"
        role="dialog"
        :aria-label="t('nav.messages')"
        data-testid="messenger-dropdown"
      >
        <div class="flex items-center justify-between px-2 pb-1 pt-1">
          <h3 class="text-xl font-bold">{{ t("messages.title") }}</h3>
          <div class="flex items-center gap-1">
            <div class="relative">
              <button
                type="button"
                class="icon-btn h-9 w-9"
                :aria-label="t('messenger.options')"
                :title="t('messenger.options')"
                aria-haspopup="menu"
                :aria-expanded="optionsOpen"
                data-testid="messenger-options"
                @click="optionsOpen = !optionsOpen"
              >
                <MoreHorizontal class="h-5 w-5" />
              </button>
              <div v-if="optionsOpen" class="popover absolute end-0 z-50 mt-1 w-60 p-1" role="menu">
                <RouterLink
                  v-for="f in FOLDER_LINKS"
                  :key="f.folder"
                  :to="{ path: '/messages', query: { folder: f.folder } }"
                  class="flex items-center gap-3 rounded-lg px-3 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-800"
                  role="menuitem"
                  :data-testid="`messenger-folder-${f.folder}`"
                  @click="close"
                >
                  <component :is="f.icon" class="h-4 w-4 text-gray-500" aria-hidden="true" />
                  <span class="flex-1">{{ t(f.label) }}</span>
                  <span v-if="f.folder === 'requests' && chatUnread.requests > 0" class="badge">{{ badgeText(chatUnread.requests) }}</span>
                </RouterLink>
              </div>
            </div>
            <button
              type="button"
              class="icon-btn h-9 w-9"
              :aria-label="t('messenger.newMessage')"
              :title="t('messenger.newMessage')"
              data-testid="messenger-new"
              @click="startNew"
            >
              <PenSquare class="h-5 w-5" />
            </button>
          </div>
        </div>

        <form class="px-2 py-1" role="search" @submit.prevent="search">
          <label class="relative block">
            <span class="sr-only">{{ t("messenger.searchMessenger") }}</span>
            <Search class="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden="true" />
            <input
              v-model="query"
              class="w-full rounded-full bg-gray-100 py-2 pe-3 ps-9 text-sm outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:bg-gray-800"
              :placeholder="t('messenger.searchMessenger')"
              dir="auto"
              data-testid="messenger-search"
            />
          </label>
        </form>

        <div class="flex gap-1 px-2 py-1" role="group" :aria-label="t('messenger.folders.label')">
          <button
            v-for="f in ([false, true] as const)"
            :key="String(f)"
            type="button"
            class="rounded-full px-3 py-1.5 text-sm font-semibold"
            :class="unreadOnly === f ? 'bg-brand-50 text-brand-700 dark:bg-brand-950/60 dark:text-brand-200' : 'text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-800'"
            :aria-pressed="unreadOnly === f"
            :data-testid="`messenger-filter-${f ? 'unread' : 'all'}`"
            @click="unreadOnly = f"
          >
            {{ f ? t("messenger.filters.unread") : t("messenger.filters.all") }}
          </button>
        </div>

        <RouterLink
          v-if="chatUnread.requests > 0"
          :to="{ path: '/messages', query: { folder: 'requests' } }"
          class="mx-2 my-1 flex items-center gap-2 rounded-xl bg-gray-50 px-3 py-2 text-sm font-semibold hover:bg-gray-100 dark:bg-gray-800/60 dark:hover:bg-gray-800"
          data-testid="messenger-requests-banner"
          @click="close"
        >
          <Inbox class="h-4 w-4 text-brand-600" aria-hidden="true" />
          {{ t("messenger.request.badge", chatUnread.requests) }}
        </RouterLink>

        <div class="min-h-0 flex-1 overflow-y-auto">
          <MessagesPanel :limit="8" :unread="unreadOnly" @navigate="close" />
        </div>

        <RouterLink
          to="/messages"
          class="mt-1 block border-t border-gray-100 px-2 pt-2 text-center text-sm font-semibold text-brand-600 hover:underline dark:border-gray-800 dark:text-brand-300"
          data-testid="messenger-see-all"
          @click="close"
        >
          {{ t("messenger.seeAll") }}
        </RouterLink>
      </div>
    </template>
  </div>

  <NewMessageModal v-if="composing" @close="composing = false" @done="onCreated" />
</template>
