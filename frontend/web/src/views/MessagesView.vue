<script setup lang="ts">
import {
  Archive,
  ArrowLeft,
  Bell,
  BellOff,
  ChevronDown,
  Images,
  Inbox,
  Info,
  MoreVertical,
  Pin,
  Search,
  Users,
  X,
} from "lucide-vue-next";
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import ChatSearch from "@/components/chat/ChatSearch.vue";
import ConversationList from "@/components/chat/ConversationList.vue";
import ForwardModal from "@/components/chat/ForwardModal.vue";
import GroupPanel from "@/components/chat/GroupPanel.vue";
import NewGroupModal from "@/components/chat/NewGroupModal.vue";
import MessageBubble from "@/components/chat/MessageBubble.vue";
import MessageComposer, { type ComposerAttachment } from "@/components/chat/MessageComposer.vue";
import SharedMediaPanel from "@/components/chat/SharedMediaPanel.vue";
import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import {
  advancePointer,
  applyReaction,
  canDeleteForEveryone,
  canEdit,
  deliveryStatus,
  mergeMessages,
  withoutMessage,
} from "@/lib/chat";
import { relativeTime } from "@/lib/format";
import type { VoiceNote } from "@/lib/useVoiceRecorder";
import { realtime } from "@/lib/ws";
import { chatService } from "@/services/chat";
import { useAuthStore } from "@/stores/auth";
import { useChatUnreadStore } from "@/stores/chatUnread";
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
const chatUnread = useChatUnreadStore();

// How far back to look for the overlap with what's loaded after a reconnect.
const MAX_CATCH_UP_PAGES = 5;
// How far back "jump to message" pages history before giving up.
const MAX_JUMP_PAGES = 10;
const OLDER_RETRY_MS = 5000;
const SEND_FAILED = {
  network_error: "errors.sendFailed",
  server_error: "errors.sendFailed",
  internal_error: "errors.sendFailed",
  dependency_unavailable: "errors.sendFailed",
};

const conversations = ref<Conversation[]>([]);
// The open conversation when it is not in the folder being shown (e.g. archived).
const opened = ref<Conversation | null>(null);
const folder = ref<"inbox" | "archived">("inbox");
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
const editTarget = ref<Message | null>(null);
const forwardTarget = ref<Message | null>(null);
const atBottom = ref(true);
const hasNew = ref(false);
const searchingAll = ref(false);
const sidePanel = ref<"search" | "media" | null>(null);
const showConversationMenu = ref(false);
let pendingJump = "";

let typingTimer: number | null = null;
let unsubs: Array<() => void> = [];
// Guards against a slow response landing after the conversation changed.
let loadGeneration = 0;
let markedReadId = "";
let syncing = false;
let syncAgain = false;

const myId = computed(() => auth.account?.id ?? "");
const activeConversation = computed(
  () =>
    conversations.value.find((c) => c.id === activeId.value) ??
    (opened.value?.id === activeId.value ? opened.value : null),
);
const isGroup = computed(() => activeConversation.value?.type === "group");
const isGroupAdmin = computed(
  () =>
    activeConversation.value?.member_states.find((s) => s.account_id === myId.value)?.role === "admin",
);
const canPin = computed(() => !isGroup.value || isGroupAdmin.value);
const pinnedIds = computed(
  () => new Set(activeConversation.value?.pinned_messages.map((p) => p.id) ?? []),
);
const showNewGroup = ref(false);
const showGroupPanel = ref(false);
const showAddMembers = ref(false);
const showMuteMenu = ref(false);
const MUTE_OPTIONS = [
  { minutes: 60, label: "messages.muteHour" },
  { minutes: 480, label: "messages.muteEightHours" },
  { minutes: 10080, label: "messages.muteWeek" },
];
const activePeerId = computed(() => {
  const c = activeConversation.value;
  if (!c || c.type === "group") return "";
  return c.members.find((m) => m !== myId.value) ?? c.members[0] ?? "";
});
const peerLastSeen = computed(() => presence.lastSeen(activePeerId.value));

function titleOf(c: Conversation): string {
  if (c.title) return c.title;
  const others = c.members.filter((m) => m !== myId.value);
  return others.map((m) => directory.label(m)).join("، ") || t("messages.groupFallback");
}
const activeTitle = computed(() => (activeConversation.value ? titleOf(activeConversation.value) : ""));

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

function statusOf(m: Message) {
  return deliveryStatus(m, activeConversation.value?.member_states ?? [], myId.value);
}
function replyName(m: Message): string {
  const sender = m.reply_preview?.sender_id ?? (m.reply_to_id ? messagesById.value[m.reply_to_id]?.sender_id : "");
  return sender ? nameOf(sender) : "";
}

function findConversation(id: unknown): Conversation | undefined {
  if (typeof id !== "string") return undefined;
  return conversations.value.find((c) => c.id === id) ?? (opened.value?.id === id ? opened.value : undefined);
}
function myState(c: Conversation | undefined) {
  return c?.member_states.find((s) => s.account_id === myId.value);
}

async function loadConversations(silent = false) {
  if (!silent) loadingList.value = true;
  listError.value = false;
  const archived = folder.value === "archived";
  try {
    const page = await chatService.conversationsPage(undefined, archived);
    conversations.value = page.data;
    // The open conversation may sit beyond the first page.
    let next = page.page.next_cursor;
    while (next && activeId.value && !conversations.value.some((c) => c.id === activeId.value)) {
      const more = await chatService.conversationsPage(next, archived);
      conversations.value.push(...more.data);
      next = more.page.next_cursor;
    }
    // ...or in the other folder.
    if (activeId.value && !conversations.value.some((c) => c.id === activeId.value)) {
      opened.value = await chatService.get(activeId.value).catch(() => null);
    }
  } catch {
    if (!silent) listError.value = true;
  } finally {
    loadingList.value = false;
  }
}

const FOLDERS = ["inbox", "archived"] as const;

function onMediaJump(messageId: string) {
  sidePanel.value = null;
  void jumpTo(messageId);
}

function setFolder(next: "inbox" | "archived") {
  if (folder.value === next) return;
  folder.value = next;
  void loadConversations();
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
    if (pendingJump) {
      const target = pendingJump;
      pendingJump = "";
      await jumpTo(target);
    }
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

/** Refetch one message (edited, or deleted for everyone) and merge it in. */
async function refreshMessage(messageId: string) {
  if (!messagesById.value[messageId]) return;
  try {
    const fresh = await chatService.message(messageId);
    messages.value = mergeMessages(messages.value, [fresh]);
  } catch {
    // Hidden from us now (moderation, or deleted for me elsewhere).
    messages.value = withoutMessage(messages.value, messageId);
  }
}

function markLatestRead() {
  const id = activeId.value;
  const last = messages.value.at(-1);
  if (!id || !last || last.id === markedReadId) return;
  markedReadId = last.id;
  const conversation = findConversation(id);
  const mine = myState(conversation);
  if (mine) advancePointer(mine, "last_read_seq", last.seq);
  if (conversation) conversation.unread_count = 0;
  chatService
    .markRead(id, last.id)
    .then(() => chatUnread.refresh())
    .catch(() => {
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
  searchingAll.value = false;
  router.push(`/messages/${id}`);
}

function onReply(m: Message) {
  editTarget.value = null;
  replyTarget.value = m;
}

async function send({ body, attachment }: { body: string; attachment: ComposerAttachment | null }) {
  if (!activeId.value) return;
  const replyToId = replyTarget.value?.id ?? null;
  try {
    const payload = attachment
      ? {
          body,
          attachments: [
            {
              media_id: attachment.media_id,
              kind: attachment.kind,
              duration_ms: null,
              file_name: attachment.file_name,
            },
          ],
          reply_to_id: replyToId,
        }
      : { body, reply_to_id: replyToId };
    const msg = await chatService.send(activeId.value, payload);
    messages.value = mergeMessages(messages.value, [msg]);
    replyTarget.value = null;
    await scrollToBottom();
  } catch (e) {
    toasts.error(e, SEND_FAILED);
    composer.value?.restore(body, attachment?.media_id ?? null);
  }
}

async function sendVoice(note: VoiceNote) {
  const id = activeId.value;
  if (!id) return;
  try {
    const asset = await chatService.upload(note.file, "voice");
    const message = await chatService.sendVoice(id, asset.id, Math.max(1, note.durationMs));
    if (id === activeId.value) {
      messages.value = mergeMessages(messages.value, [message]);
      await scrollToBottom();
    }
  } catch (e) {
    toasts.error(e, SEND_FAILED);
  }
}

function onEdit(m: Message) {
  replyTarget.value = null;
  editTarget.value = m;
}

async function saveEdit({ message, body }: { message: Message; body: string }) {
  try {
    const fresh = await chatService.edit(message.id, body);
    messages.value = mergeMessages(messages.value, [fresh]);
    editTarget.value = null;
  } catch (e) {
    toasts.error(e);
  }
}

async function onDelete(m: Message, scope: "me" | "everyone") {
  if (scope === "everyone" && !window.confirm(t("messages.deleteConfirm"))) return;
  try {
    await chatService.deleteMessage(m.id, scope);
    if (scope === "me") {
      messages.value = withoutMessage(messages.value, m.id);
    } else {
      messages.value = mergeMessages(messages.value, [
        { ...m, deleted: true, body: "", attachments: [], reactions: [], edited_at: null },
      ]);
      if (pinnedIds.value.has(m.id)) void refreshConversation(activeId.value);
    }
    if (editTarget.value?.id === m.id) editTarget.value = null;
  } catch (e) {
    toasts.error(e);
  }
}

function onForwarded(copies: Message[]) {
  forwardTarget.value = null;
  for (const copy of copies) {
    bumpConversation(copy.conversation_id, copy.seq);
    if (copy.conversation_id === activeId.value) {
      messages.value = mergeMessages(messages.value, [copy]);
      void scrollToBottom();
    }
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

async function refreshConversation(id: string) {
  try {
    const fresh = await chatService.get(id);
    const index = conversations.value.findIndex((c) => c.id === id);
    if (index >= 0) conversations.value[index] = fresh;
    else if (opened.value?.id === id) opened.value = fresh;
    else conversations.value.unshift(fresh);
  } catch {
    // Removed from it, or it is gone.
    conversations.value = conversations.value.filter((c) => c.id !== id);
    if (id === activeId.value) router.push("/messages");
  }
}

async function onPin(message: Message, pin: boolean) {
  const id = activeId.value;
  try {
    if (pin) await chatService.pin(id, message.id);
    else await chatService.unpin(id, message.id);
    await refreshConversation(id);
  } catch (e) {
    toasts.error(e);
  }
}

async function setMute(minutes: number) {
  const id = activeId.value;
  showMuteMenu.value = false;
  try {
    await chatService.mute(id, minutes);
    await refreshConversation(id);
    void chatUnread.refresh();
  } catch (e) {
    toasts.error(e);
  }
}

async function toggleArchive() {
  const c = activeConversation.value;
  showConversationMenu.value = false;
  if (!c) return;
  try {
    const fresh = await chatService.archive(c.id, !c.archived);
    // It leaves the folder being shown, but stays open.
    conversations.value = conversations.value.filter((x) => x.id !== c.id);
    opened.value = fresh;
    void chatUnread.refresh();
  } catch (e) {
    toasts.error(e);
  }
}

async function clearChat() {
  const id = activeId.value;
  showConversationMenu.value = false;
  if (!id || !window.confirm(t("messages.clearConfirm"))) return;
  try {
    await chatService.clear(id);
    messages.value = [];
    hasOlder.value = false;
    olderCursor.value = null;
    const conversation = findConversation(id);
    if (conversation) conversation.unread_count = 0;
    void chatUnread.refresh();
  } catch (e) {
    toasts.error(e);
  }
}

/** Scroll to a message, paging back through history if it isn't loaded yet. */
async function jumpTo(messageId: string) {
  for (let i = 0; i <= MAX_JUMP_PAGES; i++) {
    await nextTick();
    const el = scroller.value?.querySelector(`[data-message-id="${messageId}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (!hasOlder.value || i === MAX_JUMP_PAGES) return;
    await loadOlder();
  }
}

function openSearchResult(m: Message) {
  sidePanel.value = null;
  if (m.conversation_id === activeId.value) {
    void jumpTo(m.id);
    return;
  }
  pendingJump = m.id;
  select(m.conversation_id);
}

function pinPreview(pin: { body: string; type: string }): string {
  if (pin.body) return pin.body;
  if (pin.type === "voice") return t("messages.voiceNote");
  if (pin.type === "video") return t("messages.video");
  if (pin.type === "file") return t("messages.file");
  return t("messages.photo");
}

function onGroupCreated(conversation: Conversation) {
  showNewGroup.value = false;
  conversations.value = [conversation, ...conversations.value.filter((c) => c.id !== conversation.id)];
  router.push(`/messages/${conversation.id}`);
}

function onMembersAdded(conversation: Conversation) {
  showAddMembers.value = false;
  void refreshConversation(conversation.id);
}

function onLeft() {
  const id = activeId.value;
  showGroupPanel.value = false;
  conversations.value = conversations.value.filter((c) => c.id !== id);
  router.push("/messages");
}

function bumpConversation(id: string, seq?: unknown, fromOther = false) {
  const c = findConversation(id);
  if (!c || (folder.value === "archived" && !conversations.value.includes(c))) {
    // New, or brought back from the archive by this message: the server knows.
    void loadConversations(true);
    return;
  }
  c.last_message_at = new Date().toISOString();
  if (typeof seq === "number" && seq > (c.last_seq ?? 0)) c.last_seq = seq;
  const reading = id === activeId.value && atBottom.value && document.visibilityState === "visible";
  if (fromOther && !reading) c.unread_count = (c.unread_count ?? 0) + 1;
  if (conversations.value.includes(c)) {
    conversations.value = [c, ...conversations.value.filter((x) => x !== c)];
  }
}

function onTyping() {
  if (!activeId.value || editTarget.value) return;
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
      bumpConversation(frame.conversation_id, frame.seq, frame.sender !== myId.value);
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
      const conversation = findConversation(frame.conversation_id);
      const state = conversation?.member_states.find((s) => s.account_id === frame.reader);
      if (!conversation || !state) return;
      advancePointer(state, "last_read_seq", frame.up_to_seq as number | null);
      state.last_read_message_id = (frame.up_to_message_id as string) ?? state.last_read_message_id;
      if (frame.reader === myId.value) {
        conversation.unread_count = Math.max(0, (conversation.last_seq ?? 0) - (state.last_read_seq ?? 0));
      }
    }),
    realtime.on("chat.message.delivered", (frame) => {
      const state = findConversation(frame.conversation_id)?.member_states.find(
        (s) => s.account_id === frame.account,
      );
      if (state) advancePointer(state, "last_delivered_seq", frame.up_to_seq as number | null);
    }),
    realtime.on("chat.message.edited", (frame) => {
      if (frame.conversation_id === activeId.value) void refreshMessage(frame.message_id as string);
    }),
    realtime.on("chat.message.deleted", (frame) => {
      if (frame.conversation_id !== activeId.value) return;
      const id = frame.message_id as string;
      if (frame.scope === "moderation") messages.value = withoutMessage(messages.value, id);
      else void refreshMessage(id);
      if (pinnedIds.value.has(id)) void refreshConversation(activeId.value);
    }),
    realtime.on("chat.message.reacted", (frame) => {
      const message = messagesById.value[frame.message_id as string];
      if (message && frame.reactor !== myId.value) {
        message.reactions = applyReaction(
          message.reactions,
          frame.reactor as string,
          (frame.type as string | null) ?? null,
        );
      }
    }),
    realtime.on("chat.conversation.changed", (frame) => {
      if (typeof frame.conversation_id === "string") void refreshConversation(frame.conversation_id);
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
  editTarget.value = null;
  hasNew.value = false;
  atBottom.value = true;
  peerTyping.value = false;
  showConversationMenu.value = false;
  if (sidePanel.value === "media") sidePanel.value = null;
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
        class="flex min-h-0 flex-col border-e border-gray-200 dark:border-gray-800"
        :class="activeId ? 'hidden md:flex' : 'flex'"
      >
        <div class="flex items-center justify-between border-b border-gray-200 px-4 py-2 dark:border-gray-800">
          <h2 class="font-bold">{{ t("messages.title") }}</h2>
          <div class="flex items-center">
            <button
              class="btn-ghost px-2"
              :aria-label="t('messages.searchAll')"
              :title="t('messages.searchAll')"
              :aria-pressed="searchingAll"
              @click="searchingAll = !searchingAll"
            >
              <X v-if="searchingAll" class="h-5 w-5" />
              <Search v-else class="h-5 w-5" />
            </button>
            <button class="btn-ghost px-2" :aria-label="t('messages.newGroup')" :title="t('messages.newGroup')" @click="showNewGroup = true">
              <Users class="h-5 w-5" />
            </button>
          </div>
        </div>
        <ChatSearch v-if="searchingAll" class="min-h-0 flex-1" :name-of="nameOf" @open="openSearchResult" />
        <template v-else>
          <div class="flex gap-1 px-3 py-2" role="tablist">
            <button
              v-for="f in FOLDERS"
              :key="f"
              role="tab"
              :aria-selected="folder === f"
              class="inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium"
              :class="folder === f ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200'"
              :data-testid="`folder-${f}`"
              @click="setFolder(f)"
            >
              <Inbox v-if="f === 'inbox'" class="h-3.5 w-3.5" />
              <Archive v-else class="h-3.5 w-3.5" />
              {{ f === "inbox" ? t("messages.inbox") : t("messages.archivedFolder") }}
            </button>
          </div>
          <div class="min-h-0 flex-1 overflow-y-auto">
            <LoadingSkeleton v-if="loadingList" :rows="4" />
            <ErrorState v-else-if="listError" @retry="loadConversations()" />
            <EmptyState v-else-if="conversations.length === 0">
              {{ folder === "archived" ? t("messages.noArchived") : t("messages.noConversations") }}
            </EmptyState>
            <ConversationList
              v-else
              :conversations="conversations"
              :active-id="activeId"
              :self-id="myId"
              @select="select"
            />
          </div>
        </template>
      </div>

      <!-- Active conversation -->
      <div class="relative flex min-h-0 flex-col" :class="activeId ? 'flex' : 'hidden md:flex'">
        <template v-if="activeId">
          <header class="flex items-center gap-2 border-b border-gray-200 px-3 py-3 dark:border-gray-800">
            <button class="btn-ghost px-2 md:hidden" :aria-label="t('messages.back')" @click="router.push('/messages')">
              <ArrowLeft class="h-4 w-4 rtl:rotate-180" />
            </button>
            <RouterLink
              v-if="activePeerId && !isGroup"
              :to="{ name: 'profile-by-id', params: { id: activePeerId } }"
              class="relative shrink-0"
              :aria-label="t('nav.profile')"
            >
              <UserAvatar :name="directory.label(activePeerId)" :media-id="directory.avatarOf(activePeerId)" :size="36" />
              <span
                v-if="presence.isOnline(activePeerId)"
                class="absolute -end-0.5 -bottom-0.5 h-3 w-3 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
                data-testid="peer-online"
              />
            </RouterLink>
            <div class="min-w-0">
              <span class="block truncate text-sm font-semibold" dir="auto" data-testid="conversation-title">{{ activeTitle }}</span>
              <span class="block text-xs text-brand-500" data-testid="conversation-subtitle">
                <template v-if="peerTyping">{{ t("messages.typing") }}</template>
                <template v-else-if="isGroup">{{ t("messages.membersCount", activeConversation?.members.length ?? 0) }}</template>
                <template v-else-if="presence.isOnline(activePeerId)">{{ t("presence.online") }}</template>
                <span v-else-if="peerLastSeen" class="text-gray-500 dark:text-gray-400">
                  {{ t("messages.lastSeen", { time: relativeTime(peerLastSeen) }) }}
                </span>
              </span>
            </div>
            <div class="ms-auto flex items-center gap-1">
              <button
                class="btn-ghost px-2"
                :aria-label="t('messages.search')"
                :title="t('messages.search')"
                :aria-pressed="sidePanel === 'search'"
                @click="sidePanel = sidePanel === 'search' ? null : 'search'"
              >
                <Search class="h-5 w-5" />
              </button>
              <button
                class="btn-ghost px-2"
                :aria-label="t('messages.sharedMedia')"
                :title="t('messages.sharedMedia')"
                :aria-pressed="sidePanel === 'media'"
                @click="sidePanel = sidePanel === 'media' ? null : 'media'"
              >
                <Images class="h-5 w-5" />
              </button>
              <div class="relative">
                <button
                  class="btn-ghost px-2"
                  :aria-label="activeConversation?.muted_until ? t('messages.unmute') : t('messages.mute')"
                  :title="activeConversation?.muted_until ? t('messages.unmute') : t('messages.mute')"
                  @click="activeConversation?.muted_until ? setMute(0) : (showMuteMenu = !showMuteMenu)"
                >
                  <BellOff v-if="activeConversation?.muted_until" class="h-5 w-5 text-brand-600 dark:text-brand-300" />
                  <Bell v-else class="h-5 w-5" />
                </button>
                <template v-if="showMuteMenu">
                  <div class="fixed inset-0 z-40" @click="showMuteMenu = false" />
                  <div class="popover absolute end-0 z-50 mt-1 w-40 p-1" role="menu">
                    <button
                      v-for="option in MUTE_OPTIONS"
                      :key="option.minutes"
                      class="block w-full rounded-lg px-3 py-2 text-start text-sm hover:bg-gray-100 dark:hover:bg-gray-800"
                      role="menuitem"
                      @click="setMute(option.minutes)"
                    >
                      {{ t(option.label) }}
                    </button>
                  </div>
                </template>
              </div>
              <button v-if="isGroup" class="btn-ghost px-2" :aria-label="t('messages.groupInfo')" :title="t('messages.groupInfo')" @click="showGroupPanel = true">
                <Info class="h-5 w-5" />
              </button>
              <div class="relative">
                <button
                  class="btn-ghost px-2"
                  :aria-label="t('messages.conversationActions')"
                  :title="t('messages.conversationActions')"
                  aria-haspopup="menu"
                  :aria-expanded="showConversationMenu"
                  data-testid="conversation-menu"
                  @click="showConversationMenu = !showConversationMenu"
                >
                  <MoreVertical class="h-5 w-5" />
                </button>
                <template v-if="showConversationMenu">
                  <div class="fixed inset-0 z-40" @click="showConversationMenu = false" />
                  <div class="popover absolute end-0 z-50 mt-1 w-48 p-1" role="menu">
                    <button class="block w-full rounded-lg px-3 py-2 text-start text-sm hover:bg-gray-100 dark:hover:bg-gray-800" role="menuitem" @click="toggleArchive">
                      {{ activeConversation?.archived ? t("messages.unarchive") : t("messages.archive") }}
                    </button>
                    <button class="block w-full rounded-lg px-3 py-2 text-start text-sm text-red-600 hover:bg-gray-100 dark:hover:bg-gray-800" role="menuitem" @click="clearChat">
                      {{ t("messages.clearChat") }}
                    </button>
                  </div>
                </template>
              </div>
            </div>
          </header>

          <!-- Pinned messages -->
          <div v-if="activeConversation?.pinned_messages.length" class="border-b border-gray-200 px-3 py-1.5 dark:border-gray-800" data-testid="pinned-bar">
            <button
              v-for="pin in activeConversation.pinned_messages"
              :key="pin.id"
              class="flex w-full items-center gap-2 py-0.5 text-start text-xs text-gray-600 hover:underline dark:text-gray-300"
              @click="jumpTo(pin.id)"
            >
              <Pin class="h-3.5 w-3.5 shrink-0 text-brand-500" />
              <span class="shrink-0 font-semibold">{{ nameOf(pin.sender_id) }}</span>
              <span class="min-w-0 truncate" dir="auto">{{ pinPreview(pin) }}</span>
            </button>
          </div>

          <div
            ref="scroller"
            class="flex-1 space-y-1 overflow-y-auto p-3 [overflow-anchor:none]"
            data-testid="message-scroller"
            @scroll="onScroll"
          >
            <LoadingSkeleton v-if="loadingMessages" :rows="3" />
            <ErrorState v-else-if="messagesError" @retry="loadMessages(activeId)" />
            <template v-else>
              <p v-if="loadingOlder" class="py-1 text-center text-xs text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
              <template v-for="row in rows" :key="row.id">
                <div v-if="row.kind === 'divider'" class="my-3 text-center">
                  <span class="rounded-full bg-gray-100 px-2.5 py-0.5 text-[11px] text-gray-500 dark:bg-gray-800 dark:text-gray-400">
                    {{ row.label }}
                  </span>
                </div>
                <MessageBubble
                  v-else
                  :data-message-id="row.message.id"
                  :message="row.message"
                  :mine="row.message.sender_id === myId"
                  :self-id="myId"
                  :show-sender="isGroup"
                  :can-pin="canPin"
                  :pinned="pinnedIds.has(row.message.id)"
                  :reply-to="row.replyTo"
                  :reply-to-name="replyName(row.message)"
                  :sender-name="nameOf(row.message.sender_id)"
                  :status="statusOf(row.message)"
                  :can-edit="canEdit(row.message, myId)"
                  :can-delete-for-everyone="canDeleteForEveryone(row.message, myId)"
                  @reply="onReply"
                  @react="onReact"
                  @pin="onPin"
                  @edit="onEdit"
                  @forward="forwardTarget = $event"
                  @delete="onDelete"
                />
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
            :editing="editTarget"
            @send="send"
            @save-edit="saveEdit"
            @voice="sendVoice"
            @typing="onTyping"
            @cancel-reply="replyTarget = null"
            @cancel-edit="editTarget = null"
          />

          <!-- Side panel: search in this conversation, or its shared media -->
          <aside
            v-if="sidePanel"
            class="absolute inset-y-0 end-0 z-20 flex w-full flex-col border-s border-gray-200 bg-white shadow-pop dark:border-gray-800 dark:bg-gray-900 sm:w-80"
            :aria-label="sidePanel === 'search' ? t('messages.search') : t('messages.sharedMedia')"
          >
            <div class="flex items-center justify-between border-b border-gray-200 px-3 py-2 dark:border-gray-800">
              <h3 class="text-sm font-semibold">{{ sidePanel === "search" ? t("messages.search") : t("messages.sharedMedia") }}</h3>
              <button class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('messages.close')" @click="sidePanel = null">
                <X class="h-4 w-4" />
              </button>
            </div>
            <ChatSearch
              v-if="sidePanel === 'search'"
              class="min-h-0 flex-1"
              :conversation-id="activeId"
              :name-of="nameOf"
              @open="openSearchResult"
            />
            <SharedMediaPanel
              v-else
              :key="activeId"
              class="min-h-0 flex-1"
              :conversation-id="activeId"
              @jump="onMediaJump"
            />
          </aside>
        </template>

        <EmptyState v-else>{{ t("messages.empty") }}</EmptyState>
      </div>
    </div>

    <NewGroupModal v-if="showNewGroup" @close="showNewGroup = false" @done="onGroupCreated" />
    <NewGroupModal
      v-if="showAddMembers"
      :conversation="activeConversation"
      @close="showAddMembers = false"
      @done="onMembersAdded"
    />
    <GroupPanel
      v-if="showGroupPanel && activeConversation"
      :conversation="activeConversation"
      :self-id="myId"
      @close="showGroupPanel = false"
      @changed="refreshConversation(activeConversation!.id)"
      @left="onLeft"
      @add="showGroupPanel = false; showAddMembers = true"
    />
    <ForwardModal
      v-if="forwardTarget"
      :message="forwardTarget"
      :conversations="conversations"
      :title-of="titleOf"
      @close="forwardTarget = null"
      @done="onForwarded"
    />
  </AppShell>
</template>
