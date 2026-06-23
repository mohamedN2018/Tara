<script setup lang="ts">
import { ArrowLeft } from "lucide-vue-next";
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import ConversationList from "@/components/chat/ConversationList.vue";
import MessageBubble from "@/components/chat/MessageBubble.vue";
import MessageComposer from "@/components/chat/MessageComposer.vue";
import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { realtime } from "@/lib/ws";
import { chatService } from "@/services/chat";
import { useAuthStore } from "@/stores/auth";
import type { Conversation, Message } from "@/types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const conversations = ref<Conversation[]>([]);
const messages = ref<Message[]>([]);
const activeId = computed(() => (route.params.id as string) || "");
const loadingList = ref(true);
const loadingMessages = ref(false);
const peerTyping = ref(false);
const scroller = ref<HTMLElement | null>(null);

let typingTimer: number | null = null;
let unsubMessage: (() => void) | null = null;
let unsubTyping: (() => void) | null = null;

const myId = computed(() => auth.account?.id ?? "");

async function loadConversations() {
  loadingList.value = true;
  try {
    conversations.value = await chatService.conversations();
  } catch {
    conversations.value = [];
  } finally {
    loadingList.value = false;
  }
}

async function loadMessages(id: string) {
  if (!id) {
    messages.value = [];
    return;
  }
  loadingMessages.value = true;
  try {
    const page = await chatService.messages(id);
    messages.value = page.data;
    await scrollToBottom();
    const last = messages.value.at(-1);
    if (last) chatService.markRead(id, last.id).catch(() => {});
  } catch {
    messages.value = [];
  } finally {
    loadingMessages.value = false;
  }
}

async function scrollToBottom() {
  await nextTick();
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight;
}

function select(id: string) {
  router.push(`/messages/${id}`);
}

async function send(body: string) {
  if (!activeId.value) return;
  try {
    const msg = await chatService.send(activeId.value, { body });
    messages.value.push(msg);
    await scrollToBottom();
  } catch {
    // Surface inline; keep the composer text would be lost — acceptable for now.
  }
}

function onTyping() {
  if (!activeId.value) return;
  realtime.send({ type: "typing", conversation_id: activeId.value });
}

onMounted(() => {
  loadConversations();
  loadMessages(activeId.value);

  unsubMessage = realtime.on("message", (frame) => {
    const m = frame.message as Message | undefined;
    if (m && m.conversation_id === activeId.value) {
      messages.value.push(m);
      scrollToBottom();
      chatService.markRead(activeId.value, m.id).catch(() => {});
    }
  });

  unsubTyping = realtime.on("typing", (frame) => {
    if (frame.conversation_id === activeId.value && frame.sender_id !== myId.value) {
      peerTyping.value = true;
      if (typingTimer) window.clearTimeout(typingTimer);
      typingTimer = window.setTimeout(() => (peerTyping.value = false), 2500);
    }
  });
});

onUnmounted(() => {
  unsubMessage?.();
  unsubTyping?.();
  if (typingTimer) window.clearTimeout(typingTimer);
});

watch(activeId, (id) => loadMessages(id));
</script>

<template>
  <AppShell>
    <div class="card grid h-[calc(100vh-9rem)] grid-cols-1 overflow-hidden md:grid-cols-[280px_1fr]">
      <!-- Conversation list -->
      <div
        class="border-e border-gray-200 dark:border-gray-800"
        :class="activeId ? 'hidden md:block' : 'block'"
      >
        <h2 class="border-b border-gray-200 px-4 py-3 font-bold dark:border-gray-800">
          {{ t("messages.title") }}
        </h2>
        <LoadingSkeleton v-if="loadingList" :rows="4" />
        <EmptyState v-else-if="conversations.length === 0">
          {{ t("messages.noConversations") }}
        </EmptyState>
        <ConversationList
          v-else
          :conversations="conversations"
          :active-id="activeId"
          @select="select"
        />
      </div>

      <!-- Active conversation -->
      <div class="flex flex-col" :class="activeId ? 'flex' : 'hidden md:flex'">
        <template v-if="activeId">
          <header class="flex items-center gap-2 border-b border-gray-200 px-3 py-3 dark:border-gray-800">
            <button class="btn-ghost px-2 md:hidden" @click="router.push('/messages')">
              <ArrowLeft class="h-4 w-4" />
            </button>
            <span class="text-sm font-semibold">{{ activeId.slice(0, 8) }}</span>
            <span v-if="peerTyping" class="text-xs text-brand-500">{{ t("messages.typing") }}</span>
          </header>

          <div ref="scroller" class="flex-1 space-y-2 overflow-y-auto p-3">
            <LoadingSkeleton v-if="loadingMessages" :rows="3" />
            <MessageBubble
              v-for="m in messages"
              v-else
              :key="m.id"
              :message="m"
              :mine="m.sender_id === myId"
            />
          </div>

          <MessageComposer @send="send" @typing="onTyping" />
        </template>

        <EmptyState v-else>{{ t("messages.empty") }}</EmptyState>
      </div>
    </div>
  </AppShell>
</template>
