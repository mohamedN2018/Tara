<script setup lang="ts">
// One docked mini chat window (330px) for a real conversation: header with the
// person, "Open in Messenger", minimise and close; the latest messages; the
// same composer as the inbox. New messages arrive over the realtime socket
// (frames carry ids only, so the messages themselves come over REST).
import { Maximize2, Minus, X } from "lucide-vue-next";
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import MessageBubble from "@/components/chat/MessageBubble.vue";
import MessageComposer, { type ComposerAttachment } from "@/components/chat/MessageComposer.vue";
import { httpStatus } from "@/lib/api";
import { applyReaction, conversationTitle, deliveryStatus, isTeamThread, mergeMessages, teamSenderName, teamThreadTitle } from "@/lib/chat";
import type { VoiceNote } from "@/lib/useVoiceRecorder";
import { realtime } from "@/lib/ws";
import { chatService } from "@/services/chat";
import { useAuthStore } from "@/stores/auth";
import { useChatDockStore } from "@/stores/chatDock";
import { useChatUnreadStore } from "@/stores/chatUnread";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";
import { useToastStore } from "@/stores/toasts";
import type { Conversation, Message } from "@/types";

const props = defineProps<{ conversationId: string }>();

const { t, locale } = useI18n();
const auth = useAuthStore();
const dock = useChatDockStore();
const chatUnread = useChatUnreadStore();
const directory = useDirectoryStore();
const presence = usePresenceStore();
const toasts = useToastStore();

const conversation = ref<Conversation | null>(null);
const messages = ref<Message[]>([]);
const loading = ref(true);
const scroller = ref<HTMLElement | null>(null);
const composer = ref<InstanceType<typeof MessageComposer> | null>(null);
let unsubs: Array<() => void> = [];
let markedId = "";

const myId = computed(() => auth.account?.id ?? "");
const peerId = computed(() =>
  conversation.value && conversation.value.type !== "group" && !isTeamThread(conversation.value)
    ? (conversation.value.members.find((m) => m !== myId.value) ?? "")
    : "",
);
const title = computed(() =>
  conversation.value && isTeamThread(conversation.value)
    ? teamThreadTitle(conversation.value, t)
    : conversation.value
    ? conversationTitle(conversation.value, myId.value, directory.label, locale.value, t("messages.groupFallback"))
    : "",
);
const isRequest = computed(() => conversation.value?.request_status === "pending");

function nameOf(id: string) {
  return id === myId.value ? t("messages.you") : (teamSenderName(conversation.value, id, t) ?? directory.label(id));
}

async function scrollDown() {
  await nextTick();
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight;
  markRead();
}

function markRead() {
  const last = messages.value.at(-1);
  if (!last || last.id === markedId || document.visibilityState !== "visible") return;
  markedId = last.id;
  chatService
    .markRead(props.conversationId, last.id)
    .then(() => chatUnread.refresh())
    .catch(() => (markedId = ""));
}

async function load() {
  loading.value = true;
  try {
    const [conv, page] = await Promise.all([
      chatService.get(props.conversationId),
      chatService.messages(props.conversationId),
    ]);
    conversation.value = conv;
    messages.value = page.data;
    dock.describe(props.conversationId, title.value, peerId.value);
    loading.value = false;
    await scrollDown();
  } catch (e) {
    // Gone or no longer ours: close the window quietly.
    const status = httpStatus(e);
    if (status === 403 || status === 404) dock.forget(props.conversationId);
    else toasts.error(e);
  } finally {
    loading.value = false;
  }
}

async function pullLatest() {
  try {
    const page = await chatService.messages(props.conversationId);
    messages.value = mergeMessages(messages.value, page.data);
    await scrollDown();
  } catch {
    // The next frame catches up.
  }
}

async function send({ body, attachment }: { body: string; attachment: ComposerAttachment | null }) {
  try {
    const payload = attachment
      ? {
          body,
          attachments: [{ media_id: attachment.media_id, kind: attachment.kind, duration_ms: null, file_name: attachment.file_name }],
        }
      : { body };
    const msg = await chatService.send(props.conversationId, payload);
    messages.value = mergeMessages(messages.value, [msg]);
    if (conversation.value) conversation.value.request_status = "none";
    await scrollDown();
  } catch (e) {
    toasts.error(e);
    composer.value?.restore(body, attachment?.media_id ?? null);
  }
}

async function sendVoice(note: VoiceNote) {
  try {
    const asset = await chatService.upload(note.file, "voice");
    const msg = await chatService.sendVoice(props.conversationId, asset.id, Math.max(1, note.durationMs));
    messages.value = mergeMessages(messages.value, [msg]);
    await scrollDown();
  } catch (e) {
    toasts.error(e);
  }
}

async function onReact(message: Message, type: string | null) {
  const previous = message.reactions;
  message.reactions = applyReaction(previous, myId.value, type);
  try {
    if (type) await chatService.react(message.id, type);
    else await chatService.unreact(message.id);
  } catch (e) {
    message.reactions = previous;
    toasts.error(e);
  }
}

async function accept() {
  try {
    conversation.value = await chatService.answerRequest(props.conversationId, "accept");
    void chatUnread.refresh();
  } catch (e) {
    toasts.error(e);
  }
}

onMounted(() => {
  void load();
  realtime.send({ action: "subscribe", conversation_id: props.conversationId });
  unsubs = [
    realtime.on("chat.message.created", (f) => {
      if (f.conversation_id === props.conversationId && !messages.value.some((m) => m.id === f.message_id)) void pullLatest();
    }),
    realtime.on("chat.message.reacted", (f) => {
      const m = messages.value.find((x) => x.id === f.message_id);
      if (m && f.reactor !== myId.value) m.reactions = applyReaction(m.reactions, f.reactor as string, (f.type as string | null) ?? null);
    }),
    realtime.on("chat.message.read", (f) => {
      const state = conversation.value?.member_states.find((s) => s.account_id === f.reader);
      if (f.conversation_id === props.conversationId && state) {
        state.last_read_message_id = (f.up_to_message_id as string) ?? state.last_read_message_id;
        if (typeof f.up_to_seq === "number") state.last_read_seq = Math.max(state.last_read_seq ?? 0, f.up_to_seq);
      }
    }),
    realtime.on("_reconnected", () => void pullLatest()),
  ];
});
onUnmounted(() => {
  unsubs.forEach((u) => u());
  realtime.send({ action: "unsubscribe", conversation_id: props.conversationId });
});
</script>

<template>
  <section
    class="flex h-[28rem] w-[20.5rem] flex-col overflow-hidden rounded-t-xl border border-gray-200 bg-white shadow-pop dark:border-gray-800 dark:bg-gray-900"
    :aria-label="title"
    data-testid="chat-window"
  >
    <header class="flex items-center gap-2 border-b border-gray-200 px-2 py-1.5 dark:border-gray-800">
      <RouterLink
        v-if="peerId"
        :to="{ name: 'profile-by-id', params: { id: peerId } }"
        class="relative shrink-0"
        :aria-label="t('nav.profile')"
      >
        <UserAvatar :name="title" :media-id="directory.avatarOf(peerId)" :size="32" />
        <span
          v-if="presence.isOnline(peerId)"
          class="absolute -bottom-0.5 -end-0.5 h-3 w-3 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
        />
      </RouterLink>
      <UserAvatar v-else :name="title" :size="32" />
      <span class="min-w-0 flex-1">
        <span class="block truncate text-sm font-semibold" dir="auto">{{ title }}</span>
        <span v-if="peerId && presence.isOnline(peerId)" class="block text-[11px] text-green-600 dark:text-green-400">{{ t("presence.online") }}</span>
      </span>
      <RouterLink
        :to="`/messages/${conversationId}`"
        class="rounded-full p-1.5 text-brand-600 hover:bg-gray-100 dark:text-brand-300 dark:hover:bg-gray-800"
        :aria-label="t('messenger.dock.openInMessenger')"
        :title="t('messenger.dock.openInMessenger')"
        data-testid="chat-window-open"
      >
        <Maximize2 class="h-4 w-4" />
      </RouterLink>
      <button
        type="button"
        class="rounded-full p-1.5 text-brand-600 hover:bg-gray-100 dark:text-brand-300 dark:hover:bg-gray-800"
        :aria-label="t('messenger.dock.minimise')"
        :title="t('messenger.dock.minimise')"
        data-testid="chat-window-minimise"
        @click="dock.minimise(conversationId)"
      >
        <Minus class="h-4 w-4" />
      </button>
      <button
        type="button"
        class="rounded-full p-1.5 text-brand-600 hover:bg-gray-100 dark:text-brand-300 dark:hover:bg-gray-800"
        :aria-label="t('messenger.dock.close')"
        :title="t('messenger.dock.close')"
        data-testid="chat-window-close"
        @click="dock.close(conversationId)"
      >
        <X class="h-4 w-4" />
      </button>
    </header>

    <div ref="scroller" class="min-h-0 flex-1 space-y-1 overflow-y-auto p-2" data-testid="chat-window-messages">
      <p v-if="loading" class="py-4 text-center text-xs text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
      <template v-for="m in messages" v-else :key="m.id">
        <MessageBubble
          v-if="m.type !== 'system'"
          :message="m"
          :mine="m.sender_id === myId"
          :self-id="myId"
          :show-sender="conversation?.type === 'group'"
          :sender-name="nameOf(m.sender_id)"
          :status="deliveryStatus(m, conversation?.member_states ?? [], myId)"
          @react="onReact"
        />
      </template>
    </div>

    <div v-if="isRequest" class="border-t border-gray-200 px-3 py-2 text-center text-xs dark:border-gray-800">
      <p class="mb-1" dir="auto">{{ t("messenger.request.title", { name: title }) }}</p>
      <button type="button" class="btn-primary px-3 py-1 text-xs" @click="accept">{{ t("messenger.request.accept") }}</button>
    </div>
    <MessageComposer ref="composer" :key="conversationId" @send="send" @voice="sendVoice" />
  </section>
</template>
