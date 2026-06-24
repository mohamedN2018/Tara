<script setup lang="ts">
import { ArrowLeft, ChevronDown } from "lucide-vue-next";
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import ConversationList from "@/components/chat/ConversationList.vue";
import MessageBubble from "@/components/chat/MessageBubble.vue";
import MessageComposer from "@/components/chat/MessageComposer.vue";
import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { realtime } from "@/lib/ws";
import { chatService } from "@/services/chat";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";
import type { Conversation, Message } from "@/types";

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const presence = usePresenceStore();
const directory = useDirectoryStore();

const conversations = ref<Conversation[]>([]);
const messages = ref<Message[]>([]);
const activeId = computed(() => (route.params.id as string) || "");
const loadingList = ref(true);
const loadingMessages = ref(false);
const peerTyping = ref(false);
const scroller = ref<HTMLElement | null>(null);

const replyTarget = ref<Message | null>(null);
const peerReadUpToId = ref<string | null>(null);
const atBottom = ref(true);
const hasNew = ref(false);

let typingTimer: number | null = null;
let unsubMessage: (() => void) | null = null;
let unsubTyping: (() => void) | null = null;
let unsubRead: (() => void) | null = null;

const myId = computed(() => auth.account?.id ?? "");
const activeConversation = computed(
  () => conversations.value.find((c) => c.id === activeId.value) ?? null,
);
const activePeerId = computed(() => {
  const c = activeConversation.value;
  if (!c) return "";
  return c.members.find((m) => m !== myId.value) ?? c.members[0] ?? "";
});

function nameOf(senderId: string): string {
  if (senderId === myId.value) return t("messages.you");
  return directory.nameOf(senderId) || senderId.slice(0, 8);
}

const messagesById = computed(() => {
  const map: Record<string, Message> = {};
  for (const m of messages.value) map[m.id] = m;
  return map;
});

function dateLabel(d: Date): string {
  const today = new Date();
  const yest = new Date();
  yest.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return t("messages.today");
  if (d.toDateString() === yest.toDateString()) return t("messages.yesterday");
  return d.toLocaleDateString(locale.value, { day: "numeric", month: "long", year: "numeric" });
}

type Row =
  | { kind: "divider"; id: string; label: string }
  | { kind: "msg"; id: string; message: Message; replyTo: Message | null };

const rows = computed<Row[]>(() => {
  const out: Row[] = [];
  let lastDay = "";
  for (const m of messages.value) {
    const d = new Date(m.created_at);
    const key = d.toDateString();
    if (key !== lastDay) {
      lastDay = key;
      out.push({ kind: "divider", id: `d-${key}`, label: dateLabel(d) });
    }
    out.push({
      kind: "msg",
      id: m.id,
      message: m,
      replyTo: m.reply_to_id ? (messagesById.value[m.reply_to_id] ?? null) : null,
    });
  }
  return out;
});

const lastMineId = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].sender_id === myId.value) return messages.value[i].id;
  }
  return null;
});
const peerSeen = computed(() => {
  if (!peerReadUpToId.value || !lastMineId.value) return false;
  const ri = messages.value.findIndex((m) => m.id === peerReadUpToId.value);
  const mi = messages.value.findIndex((m) => m.id === lastMineId.value);
  return ri >= 0 && mi >= 0 && ri >= mi;
});

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

async function loadMessages(id: string, silent = false) {
  if (!id) {
    messages.value = [];
    return;
  }
  if (!silent) loadingMessages.value = true;
  try {
    const wasAtBottom = atBottom.value;
    const page = await chatService.messages(id);
    const grew = page.data.length > messages.value.length;
    messages.value = page.data;
    if (!silent || wasAtBottom) await scrollToBottom();
    else if (grew) hasNew.value = true;
    const last = messages.value.at(-1);
    if (last) chatService.markRead(id, last.id).catch(() => {});
  } catch {
    if (!silent) messages.value = [];
  } finally {
    loadingMessages.value = false;
  }
}

async function scrollToBottom() {
  await nextTick();
  if (scroller.value) {
    scroller.value.scrollTop = scroller.value.scrollHeight;
    atBottom.value = true;
    hasNew.value = false;
  }
}

function onScroll() {
  const el = scroller.value;
  if (!el) return;
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  if (atBottom.value) hasNew.value = false;
}

function select(id: string) {
  router.push(`/messages/${id}`);
}

function onReply(m: Message) {
  replyTarget.value = m;
}

async function send({ body, mediaId }: { body: string; mediaId: string | null }) {
  if (!activeId.value) return;
  const replyToId = replyTarget.value?.id ?? null;
  try {
    const payload = mediaId
      ? {
          body,
          type: "image",
          attachments: [{ media_id: mediaId, kind: "image", duration_ms: null }],
          reply_to_id: replyToId,
        }
      : { body, reply_to_id: replyToId };
    const msg = await chatService.send(activeId.value, payload);
    messages.value.push(msg);
    replyTarget.value = null;
    await scrollToBottom();
  } catch {
    // Keep the composer responsive; the send simply didn't go through.
  }
}

function onTyping() {
  if (!activeId.value) return;
  realtime.send({ action: "typing", conversation_id: activeId.value });
}

function subscribe(id: string) {
  if (id) realtime.send({ action: "subscribe", conversation_id: id });
}
function unsubscribe(id: string) {
  if (id) realtime.send({ action: "unsubscribe", conversation_id: id });
}

onMounted(() => {
  loadConversations();
  loadMessages(activeId.value);
  subscribe(activeId.value);

  unsubMessage = realtime.on("chat.message.created", (frame) => {
    if (frame.conversation_id === activeId.value) loadMessages(activeId.value, true);
  });
  unsubTyping = realtime.on("conversation.typing", (frame) => {
    if (frame.conversation_id === activeId.value && frame.actor_id !== myId.value) {
      peerTyping.value = true;
      if (typingTimer) window.clearTimeout(typingTimer);
      typingTimer = window.setTimeout(() => (peerTyping.value = false), 2500);
    }
  });
  unsubRead = realtime.on("chat.message.read", (frame) => {
    if (frame.conversation_id === activeId.value && frame.reader !== myId.value) {
      peerReadUpToId.value = (frame.up_to_message_id as string) ?? null;
    }
  });
});

onUnmounted(() => {
  unsubMessage?.();
  unsubTyping?.();
  unsubRead?.();
  unsubscribe(activeId.value);
  if (typingTimer) window.clearTimeout(typingTimer);
});

watch(activeId, (id, prev) => {
  if (prev) unsubscribe(prev);
  subscribe(id);
  replyTarget.value = null;
  peerReadUpToId.value = null;
  hasNew.value = false;
  atBottom.value = true;
  loadMessages(id);
});
</script>

<template>
  <AppShell :right="false">
    <div class="card grid h-[calc(100vh-7rem)] grid-cols-1 overflow-hidden md:grid-cols-[280px_1fr]">
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
          :self-id="myId"
          @select="select"
        />
      </div>

      <!-- Active conversation -->
      <div class="relative flex flex-col" :class="activeId ? 'flex' : 'hidden md:flex'">
        <template v-if="activeId">
          <header class="flex items-center gap-2 border-b border-gray-200 px-3 py-3 dark:border-gray-800">
            <button class="btn-ghost px-2 md:hidden" @click="router.push('/messages')">
              <ArrowLeft class="h-4 w-4" />
            </button>
            <RouterLink
              v-if="activePeerId"
              :to="{ name: 'profile-by-id', params: { id: activePeerId } }"
              class="relative shrink-0"
            >
              <UserAvatar :name="directory.nameOf(activePeerId) || activePeerId" :size="36" />
              <span
                v-if="presence.isOnline(activePeerId)"
                class="absolute -end-0.5 -bottom-0.5 h-3 w-3 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
              />
            </RouterLink>
            <div class="min-w-0">
              <span class="block truncate text-sm font-semibold">
                {{ directory.nameOf(activePeerId) || (activePeerId || activeId).slice(0, 8) }}
              </span>
              <span class="block text-xs text-brand-500">
                <template v-if="peerTyping">{{ t("messages.typing") }}</template>
                <template v-else-if="presence.isOnline(activePeerId)">{{ t("presence.online") }}</template>
              </span>
            </div>
          </header>

          <div ref="scroller" class="flex-1 space-y-1 overflow-y-auto p-3" @scroll="onScroll">
            <LoadingSkeleton v-if="loadingMessages" :rows="3" />
            <template v-else>
              <template v-for="row in rows" :key="row.id">
                <div v-if="row.kind === 'divider'" class="my-3 text-center">
                  <span class="rounded-full bg-gray-100 px-2.5 py-0.5 text-[11px] text-gray-500 dark:bg-gray-800">
                    {{ row.label }}
                  </span>
                </div>
                <template v-else>
                  <MessageBubble
                    :message="row.message"
                    :mine="row.message.sender_id === myId"
                    :reply-to="row.replyTo"
                    :reply-to-name="row.replyTo ? nameOf(row.replyTo.sender_id) : ''"
                    @reply="onReply"
                  />
                  <p
                    v-if="row.message.id === lastMineId && peerSeen"
                    class="pe-1 pt-0.5 text-end text-[10px] text-gray-400"
                  >
                    ✓ {{ t("messages.seen") }}
                  </p>
                </template>
              </template>
            </template>
          </div>

          <!-- Jump to latest -->
          <button
            v-if="hasNew"
            class="absolute bottom-20 start-1/2 z-10 -translate-x-1/2 rounded-full bg-brand-600 px-3 py-1 text-xs font-medium text-white shadow-lg"
            @click="scrollToBottom"
          >
            <ChevronDown class="inline h-3.5 w-3.5" /> {{ t("messages.newMessages") }}
          </button>

          <MessageComposer
            :replying-to="replyTarget"
            :replying-to-name="replyTarget ? nameOf(replyTarget.sender_id) : ''"
            @send="send"
            @typing="onTyping"
            @cancel-reply="replyTarget = null"
          />
        </template>

        <EmptyState v-else>{{ t("messages.empty") }}</EmptyState>
      </div>
    </div>
  </AppShell>
</template>
