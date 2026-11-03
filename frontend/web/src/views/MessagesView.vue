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
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { isSeenByOthers, mergeMessages } from "@/lib/chat";
import { realtime } from "@/lib/ws";
import { chatService } from "@/services/chat";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";
import { useToastStore } from "@/stores/toasts";
import type { Conversation, CursorPage, Message } from "@/types";

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const presence = usePresenceStore();
const directory = useDirectoryStore();
const toasts = useToastStore();

// How far back to look for the overlap with what's loaded after a reconnect.
const MAX_CATCH_UP_PAGES = 5;
const OLDER_RETRY_MS = 5000;
const SEND_FAILED = {
  network_error: "errors.sendFailed",
  server_error: "errors.sendFailed",
  internal_error: "errors.sendFailed",
  dependency_unavailable: "errors.sendFailed",
};

const conversations = ref<Conversation[]>([]);
const messages = ref<Message[]>([]);
const activeId = computed(() => (route.params.id as string) || "");
const loadingList = ref(true);
const loadingMessages = ref(false);
const listError = ref(false);
const messagesError = ref(false);
const composer = ref<InstanceType<typeof MessageComposer> | null>(null);

// `next_cursor` of the oldest loaded page.
const olderCursor = ref<string | null>(null);
const hasOlder = ref(false);
const loadingOlder = ref(false);
let olderRetryAt = 0;
const peerTyping = ref(false);
const scroller = ref<HTMLElement | null>(null);

const replyTarget = ref<Message | null>(null);
const atBottom = ref(true);
const hasNew = ref(false);

let typingTimer: number | null = null;
let unsubs: Array<() => void> = [];
// Guards against a slow response landing after the conversation changed.
let loadGeneration = 0;
let markedReadId = "";
let syncing = false;
let syncAgain = false;

const myId = computed(() => auth.account?.id ?? "");
const activeConversation = computed(
  () => conversations.value.find((c) => c.id === activeId.value) ?? null,
);
const activePeerId = computed(() => {
  const c = activeConversation.value;
  if (!c) return "";
  return c.members.find((m) => m !== myId.value) ?? c.members[0] ?? "";
});

const activeTitle = computed(() => {
  const c = activeConversation.value;
  if (!c) return "";
  if (c.title) return c.title;
  const others = c.members.filter((m) => m !== myId.value);
  return others.map((m) => directory.label(m)).join("، ") || t("messages.groupFallback");
});

function nameOf(senderId: string): string {
  if (senderId === myId.value) return t("messages.you");
  return directory.label(senderId);
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
const peerSeen = computed(() =>
  isSeenByOthers(messages.value, activeConversation.value?.member_states ?? [], myId.value),
);

async function loadConversations(silent = false) {
  if (!silent) loadingList.value = true;
  listError.value = false;
  try {
    const page = await chatService.conversationsPage();
    conversations.value = page.data;
    // The open conversation may sit beyond the first page, and it is the only
    // source of its members (there is no single-conversation endpoint).
    let next = page.page.next_cursor;
    while (next && activeId.value && !activeConversation.value) {
      const more = await chatService.conversationsPage(next);
      conversations.value.push(...more.data);
      next = more.page.next_cursor;
    }
  } catch {
    if (!silent) listError.value = true;
  } finally {
    loadingList.value = false;
  }
}

function setOlder(page: CursorPage<Message>) {
  olderCursor.value = page.page.next_cursor;
  hasOlder.value = page.page.has_more;
}

async function loadMessages(id: string) {
  const generation = ++loadGeneration;
  messages.value = [];
  olderCursor.value = null;
  hasOlder.value = false;
  messagesError.value = false;
  markedReadId = "";
  if (!id) {
    loadingMessages.value = false;
    return;
  }
  loadingMessages.value = true;
  try {
    const page = await chatService.messages(id);
    if (generation !== loadGeneration) return;
    messages.value = page.data;
    setOlder(page);
    loadingMessages.value = false;
    await scrollToBottom();
    await fillViewport(generation);
  } catch {
    if (generation === loadGeneration) messagesError.value = true;
  } finally {
    if (generation === loadGeneration) loadingMessages.value = false;
  }
}

/** Page in history until it overflows: without a scrollbar, scroll-up can't trigger. */
async function fillViewport(generation: number) {
  while (
    generation === loadGeneration &&
    hasOlder.value &&
    scroller.value &&
    scroller.value.scrollHeight <= scroller.value.clientHeight
  ) {
    await loadOlder();
    await scrollToBottom();
    if (Date.now() < olderRetryAt) return;
  }
}

async function loadOlder() {
  const id = activeId.value;
  const cursor = olderCursor.value;
  if (!id || !cursor || !hasOlder.value || loadingOlder.value || Date.now() < olderRetryAt) return;
  const generation = loadGeneration;
  loadingOlder.value = true;
  try {
    const page = await chatService.messages(id, cursor);
    if (generation !== loadGeneration) return;
    const el = scroller.value;
    const before = el?.scrollHeight ?? 0;
    const top = el?.scrollTop ?? 0;
    messages.value = mergeMessages(messages.value, page.data);
    setOlder(page);
    loadingOlder.value = false;
    await nextTick();
    // Keep the same message under the reader's eyes.
    if (el) el.scrollTop = top + (el.scrollHeight - before);
  } catch (e) {
    olderRetryAt = Date.now() + OLDER_RETRY_MS;
    toasts.error(e);
  } finally {
    loadingOlder.value = false;
  }
}

/** Pull what's new and merge it into the list, however far it has been paged back. */
async function pullLatest(id: string) {
  const generation = loadGeneration;
  const known = new Set(messages.value.map((m) => m.id));
  const overlaps = (p: CursorPage<Message>) => p.data.some((m) => known.has(m.id));

  let page = await chatService.messages(id);
  const pages = [page];
  for (let i = 1; i < MAX_CATCH_UP_PAGES && !overlaps(page); i++) {
    if (!page.page.has_more || !page.page.next_cursor) break;
    page = await chatService.messages(id, page.page.next_cursor);
    pages.push(page);
  }
  if (generation !== loadGeneration) return;

  const fresh = pages.flatMap((p) => p.data).filter((m) => !known.has(m.id));
  if (!fresh.length) return;
  const stick = atBottom.value;
  if (known.size && overlaps(page)) {
    messages.value = mergeMessages(messages.value, fresh);
  } else {
    // Nothing connects to what's loaded: restart from the newest history
    // rather than leave a silent hole in the conversation.
    messages.value = mergeMessages([], fresh);
    setOlder(page);
  }
  if (stick) {
    await scrollToBottom();
  } else if (fresh.some((m) => m.sender_id !== myId.value)) {
    hasNew.value = true;
  }
}

async function syncLatest() {
  const id = activeId.value;
  if (!id) return;
  if (syncing) {
    syncAgain = true;
    return;
  }
  syncing = true;
  try {
    do {
      syncAgain = false;
      await pullLatest(id);
    } while (syncAgain && id === activeId.value);
  } catch {
    // The next frame, or the next reconnect, catches up.
  } finally {
    syncing = false;
  }
}

function markLatestRead() {
  const id = activeId.value;
  const last = messages.value.at(-1);
  if (!id || !last || last.id === markedReadId) return;
  markedReadId = last.id;
  chatService.markRead(id, last.id).catch(() => {
    markedReadId = ""; // Retried the next time the reader reaches the bottom.
  });
}

async function scrollToBottom() {
  await nextTick();
  if (scroller.value) {
    scroller.value.scrollTop = scroller.value.scrollHeight;
    atBottom.value = true;
    hasNew.value = false;
    markLatestRead();
  }
}

function onScroll() {
  const el = scroller.value;
  if (!el) return;
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  if (atBottom.value) {
    hasNew.value = false;
    markLatestRead();
  }
  if (el.scrollTop < 120) void loadOlder();
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
    messages.value = mergeMessages(messages.value, [msg]);
    replyTarget.value = null;
    await scrollToBottom();
  } catch (e) {
    toasts.error(e, SEND_FAILED);
    composer.value?.restore(body, mediaId);
  }
}

function bumpConversation(id: string) {
  const c = conversations.value.find((x) => x.id === id);
  if (!c) {
    void loadConversations(true);
    return;
  }
  c.last_message_at = new Date().toISOString();
  conversations.value = [c, ...conversations.value.filter((x) => x !== c)];
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

  unsubs = [
    realtime.on("chat.message.created", (frame) => {
      if (typeof frame.conversation_id !== "string") return;
      bumpConversation(frame.conversation_id);
      if (frame.conversation_id !== activeId.value) return;
      // Frames carry only a short preview, so the message itself comes over REST.
      if (!messagesById.value[frame.message_id as string]) void syncLatest();
    }),
    realtime.on("conversation.typing", (frame) => {
      if (frame.conversation_id === activeId.value && frame.actor_id !== myId.value) {
        peerTyping.value = true;
        if (typingTimer) window.clearTimeout(typingTimer);
        typingTimer = window.setTimeout(() => (peerTyping.value = false), 2500);
      }
    }),
    realtime.on("chat.message.read", (frame) => {
      const conversation = conversations.value.find((c) => c.id === frame.conversation_id);
      const state = conversation?.member_states.find((s) => s.account_id === frame.reader);
      if (state) state.last_read_message_id = (frame.up_to_message_id as string) ?? null;
    }),
    realtime.on("_reconnected", () => {
      void loadConversations(true);
      void syncLatest();
    }),
  ];
});

onUnmounted(() => {
  unsubs.forEach((u) => u());
  unsubscribe(activeId.value);
  if (typingTimer) window.clearTimeout(typingTimer);
});

watch(activeId, (id, prev) => {
  if (prev) unsubscribe(prev);
  subscribe(id);
  replyTarget.value = null;
  hasNew.value = false;
  atBottom.value = true;
  peerTyping.value = false;
  olderRetryAt = 0;
  loadMessages(id);
  if (id && !activeConversation.value) void loadConversations(true);
});
</script>

<template>
  <AppShell :right="false">
    <div class="card grid h-[calc(100vh-7rem)] grid-cols-1 grid-rows-[minmax(0,1fr)] overflow-hidden md:grid-cols-[280px_1fr]">
      <!-- Conversation list -->
      <div
        class="min-h-0 overflow-y-auto border-e border-gray-200 dark:border-gray-800"
        :class="activeId ? 'hidden md:block' : 'block'"
      >
        <h2 class="border-b border-gray-200 px-4 py-3 font-bold dark:border-gray-800">
          {{ t("messages.title") }}
        </h2>
        <LoadingSkeleton v-if="loadingList" :rows="4" />
        <ErrorState v-else-if="listError" @retry="loadConversations()" />
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
      <div class="relative flex min-h-0 flex-col" :class="activeId ? 'flex' : 'hidden md:flex'">
        <template v-if="activeId">
          <header class="flex items-center gap-2 border-b border-gray-200 px-3 py-3 dark:border-gray-800">
            <button class="btn-ghost px-2 md:hidden" :aria-label="t('messages.back')" @click="router.push('/messages')">
              <ArrowLeft class="h-4 w-4 rtl:rotate-180" />
            </button>
            <RouterLink
              v-if="activePeerId"
              :to="{ name: 'profile-by-id', params: { id: activePeerId } }"
              class="relative shrink-0"
              :aria-label="t('nav.profile')"
            >
              <UserAvatar :name="directory.label(activePeerId)" :media-id="directory.avatarOf(activePeerId)" :size="36" />
              <span
                v-if="presence.isOnline(activePeerId)"
                class="absolute -end-0.5 -bottom-0.5 h-3 w-3 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
              />
            </RouterLink>
            <div class="min-w-0">
              <span class="block truncate text-sm font-semibold" dir="auto" data-testid="conversation-title">{{ activeTitle }}</span>
              <span class="block text-xs text-brand-500">
                <template v-if="peerTyping">{{ t("messages.typing") }}</template>
                <template v-else-if="presence.isOnline(activePeerId)">{{ t("presence.online") }}</template>
              </span>
            </div>
          </header>

          <div
            ref="scroller"
            class="flex-1 space-y-1 overflow-y-auto p-3 [overflow-anchor:none]"
            data-testid="message-scroller"
            @scroll="onScroll"
          >
            <LoadingSkeleton v-if="loadingMessages" :rows="3" />
            <ErrorState v-else-if="messagesError" @retry="loadMessages(activeId)" />
            <template v-else>
              <p v-if="loadingOlder" class="py-1 text-center text-xs text-gray-400">{{ t("states.loading") }}</p>
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
                    :sender-name="nameOf(row.message.sender_id)"
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
            class="absolute inset-x-0 bottom-20 z-10 mx-auto w-fit rounded-full bg-brand-600 px-3 py-1 text-xs font-medium text-white shadow-lg"
            @click="scrollToBottom"
          >
            <ChevronDown class="inline h-3.5 w-3.5" /> {{ t("messages.newMessages") }}
          </button>

          <MessageComposer
            ref="composer"
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
