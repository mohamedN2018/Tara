<script setup lang="ts">
import {
  Archive,
  ArrowLeft,
  Bell,
  BellOff,
  ChevronDown,
  Images,
  Info,
  MoreHorizontal,
  MoreVertical,
  PenSquare,
  Pin,
  Search,
  ShieldAlert,
  Users,
  X,
} from "lucide-vue-next";
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import CallBanner from "@/components/calls/CallBanner.vue";
import CallButtons from "@/components/calls/CallButtons.vue";
import CallLogChip from "@/components/calls/CallLogChip.vue";
import ChatSearch from "@/components/chat/ChatSearch.vue";
import ConversationInfoPanel from "@/components/chat/ConversationInfoPanel.vue";
import ConversationList, { type RowAction } from "@/components/chat/ConversationList.vue";
import ListingStrip from "@/components/chat/ListingStrip.vue";
import MessageReportDialog from "@/components/chat/MessageReportDialog.vue";
import NewMessageModal from "@/components/chat/NewMessageModal.vue";
import ConfirmActionDialog from "@/components/social/ConfirmActionDialog.vue";
import ReportDialog from "@/components/social/ReportDialog.vue";
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
import { httpStatus } from "@/lib/api";
import {
  advancePointer,
  applyReaction,
  canDeleteForEveryone,
  canEdit,
  conversationTitle,
  deliveryStatus,
  isTeamThread,
  mergeMessages,
  seenByAt,
  teamSenderName,
  teamThreadTitle,
  typePreview,
  withoutMessage,
} from "@/lib/chat";
import { relativeTime } from "@/lib/format";
import { useEscapeKey } from "@/lib/useEscapeKey";
import type { VoiceNote } from "@/lib/useVoiceRecorder";
import { useRelationshipPrefs } from "@/lib/useRelationshipPrefs";
import { realtime } from "@/lib/ws";
import { chatService, type ChatFolder } from "@/services/chat";
import { useAuthStore } from "@/stores/auth";
import { useCallStore } from "@/stores/calls";
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
// Blocks go through the shared people-lists store so profile and post menus see them at once.
const relationshipPrefs = useRelationshipPrefs();
const chatUnread = useChatUnreadStore();
const calls = useCallStore();

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
// Inbox folders, kept in the URL (?folder=): chats, archived, message requests,
// spam (declined requests) and Marketplace (the chats of type marketplace).
type Folder = ChatFolder | "marketplace";
const FOLDERS: Folder[] = ["inbox", "requests", "archived", "marketplace", "spam"];
const PRIMARY_FOLDERS: Folder[] = ["inbox", "requests", "marketplace"];
const MORE_FOLDERS: Folder[] = ["archived", "spam"];
function folderFromQuery(value: unknown): Folder {
  return FOLDERS.includes(value as Folder) ? (value as Folder) : "inbox";
}
const folder = ref<Folder>(folderFromQuery(route.query.folder));
const folderMenuOpen = ref(false);
useEscapeKey(folderMenuOpen, () => (folderMenuOpen.value = false));
// The open secondary folder shows as a chip next to the primary ones.
const visibleFolders = computed<Folder[]>(() =>
  PRIMARY_FOLDERS.includes(folder.value) ? PRIMARY_FOLDERS : [...PRIMARY_FOLDERS, folder.value],
);
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
const searchingAll = ref(route.query.search === "1");
const initialSearch = typeof route.query.q === "string" ? route.query.q : "";
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
const showNewMessage = ref(false);
// The info column: open by default where there is room for three columns.
const showInfo = ref(typeof window !== "undefined" && !!window.matchMedia?.("(min-width: 1280px)").matches);
const reportPerson = ref<{ id: string; name: string } | null>(null);
const reportTarget = ref<Message | null>(null);
const showGroupPanel = ref(false);
const showAddMembers = ref(false);
const showMuteMenu = ref(false);
useEscapeKey(showMuteMenu, () => (showMuteMenu.value = false));
useEscapeKey(showConversationMenu, () => (showConversationMenu.value = false));
const MUTE_OPTIONS = [
  { minutes: 60, label: "messages.muteHour" },
  { minutes: 480, label: "messages.muteEightHours" },
  { minutes: 10080, label: "messages.muteWeek" },
];
const activePeerId = computed(() => {
  const c = activeConversation.value;
  if (!c || c.type === "group" || isTeamThread(c)) return "";
  return c.members.find((m) => m !== myId.value) ?? c.members[0] ?? "";
});
const peerLastSeen = computed(() => presence.lastSeen(activePeerId.value));

function titleOf(c: Conversation): string {
  if (isTeamThread(c)) return teamThreadTitle(c, t);
  return conversationTitle(c, myId.value, directory.label, locale.value, t("messages.groupFallback"));
}
const activeTitle = computed(() => (activeConversation.value ? titleOf(activeConversation.value) : ""));
// A DM peer whose name is still loading: a skeleton, never a placeholder name.
const titlePending = computed(
  () => !!activeConversation.value && !activeConversation.value.title && !!activePeerId.value && directory.pending(activePeerId.value),
);

function nameOf(senderId: string): string {
  if (senderId === myId.value) return t("messages.you");
  const team = teamSenderName(activeConversation.value, senderId, t);
  if (team) return team;
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

let listGeneration = 0;
async function loadConversations(silent = false) {
  // A folder switch or a silent reload can overlap: only the newest one lands.
  const generation = ++listGeneration;
  if (!silent) loadingList.value = true;
  listError.value = false;
  try {
    const page = await fetchFolder();
    if (generation !== listGeneration) return;
    const list = page.data;
    // The open conversation may sit beyond the first page.
    let next = page.page.next_cursor;
    while (next && activeId.value && !list.some((c) => c.id === activeId.value)) {
      const more = await fetchFolder(next);
      if (generation !== listGeneration) return;
      list.push(...more.data);
      next = more.page.next_cursor;
    }
    conversations.value = list;
    // ...or in the other folder.
    if (activeId.value && !list.some((c) => c.id === activeId.value)) {
      const other = await chatService.get(activeId.value).catch(() => null);
      if (generation === listGeneration) opened.value = other;
    }
  } catch {
    if (!silent && generation === listGeneration) listError.value = true;
  } finally {
    if (generation === listGeneration) loadingList.value = false;
  }
}

function fetchFolder(cursor?: string | null) {
  const f = folder.value;
  return chatService.folderPage(f === "marketplace" ? { cursor, type: "marketplace" } : { cursor, folder: f });
}

/** Whether a conversation belongs in the folder being shown. */
function inFolder(c: Conversation): boolean {
  const request = c.request_status && c.request_status !== "none" ? c.request_status : "";
  if (folder.value === "requests") return request === "pending";
  if (folder.value === "spam") return request === "spam";
  if (request) return false;
  if (folder.value === "marketplace") return c.type === "marketplace" && !c.archived;
  return !!c.archived === (folder.value === "archived");
}

function onMediaJump(messageId: string) {
  sidePanel.value = null;
  void jumpTo(messageId);
}

function setFolder(next: Folder) {
  if (folder.value === next) return;
  folder.value = next;
  searchingAll.value = false;
  void router.replace({
    query: { ...route.query, folder: next === "inbox" ? undefined : next, search: undefined, q: undefined },
  });
  void loadConversations();
}

// Back/forward, or a menu link to another folder while the inbox is open.
watch(
  () => route.query.folder,
  (value) => {
    const next = folderFromQuery(value);
    if (next === folder.value) return;
    folder.value = next;
    void loadConversations();
  },
);
watch(
  () => route.query.search,
  (value) => {
    if (value === "1") searchingAll.value = true;
  },
);

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
    // Nothing loaded (busy, at the end, or backing off): looping again would
    // only spin on microtasks and freeze the tab.
    if (!(await loadOlder())) return;
    await scrollToBottom();
  }
}

/** True when an older page was merged in. */
async function loadOlder(): Promise<boolean> {
  const id = activeId.value;
  const cursor = olderCursor.value;
  if (!id || !cursor || !hasOlder.value || loadingOlder.value || Date.now() < olderRetryAt) return false;
  const generation = loadGeneration;
  loadingOlder.value = true;
  try {
    const page = await chatService.messages(id, cursor);
    if (generation !== loadGeneration) return false;
    const el = scroller.value;
    const before = el?.scrollHeight ?? 0;
    const top = el?.scrollTop ?? 0;
    messages.value = mergeMessages(messages.value, page.data);
    setOlder(page);
    loadingOlder.value = false;
    await nextTick();
    // Keep the same message under the reader's eyes.
    if (el) el.scrollTop = top + (el.scrollHeight - before);
    return true;
  } catch (e) {
    olderRetryAt = Date.now() + OLDER_RETRY_MS;
    toasts.error(e);
    return false;
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
  // A frame for the conversation opened meanwhile asked for a sync too.
  if (syncAgain && id !== activeId.value) void syncLatest();
}

/** Refetch one message (edited, or deleted for everyone) and merge it in. */
async function refreshMessage(messageId: string) {
  if (!messagesById.value[messageId]) return;
  const generation = loadGeneration;
  try {
    const fresh = await chatService.message(messageId);
    if (generation === loadGeneration) messages.value = mergeMessages(messages.value, [fresh]);
  } catch {
    // Hidden from us now (moderation, or deleted for me elsewhere).
    if (generation === loadGeneration) messages.value = withoutMessage(messages.value, messageId);
  }
}

function markLatestRead() {
  const id = activeId.value;
  const last = messages.value.at(-1);
  // A background tab has not been read: `onVisible` catches up when it is shown.
  if (document.visibilityState !== "visible") return;
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

// The info column opening (or the window resizing) narrows the pane and wraps
// lines: whoever was reading the newest message stays there.
let paneObserver: ResizeObserver | null = null;
watch(scroller, (el, previous) => {
  if (previous) paneObserver?.unobserve(previous);
  if (!el || typeof ResizeObserver === "undefined") return;
  paneObserver ??= new ResizeObserver(() => {
    const pane = scroller.value;
    if (pane && atBottom.value) pane.scrollTop = pane.scrollHeight;
  });
  paneObserver.observe(el);
});

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
  // Stay in the folder being shown (requests, archived, ...).
  router.push({ path: `/messages/${id}`, query: folder.value === "inbox" ? {} : { folder: folder.value } });
}

function onReply(m: Message) {
  editTarget.value = null;
  replyTarget.value = m;
}

async function send({ body, attachment }: { body: string; attachment: ComposerAttachment | null }) {
  const id = activeId.value;
  if (!id) return;
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
    const msg = await chatService.send(id, payload);
    if (id !== activeId.value) return; // switched away while sending
    messages.value = mergeMessages(messages.value, [msg]);
    replyTarget.value = null;
    await scrollToBottom();
  } catch (e) {
    toasts.error(e, SEND_FAILED);
    // Removed from the conversation meanwhile (404): take it off the list.
    if (httpStatus(e) === 404) void refreshConversation(id);
    // The composer is per conversation: never refill another one's.
    else if (id === activeId.value) composer.value?.restore(body, attachment?.media_id ?? null);
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
    if (httpStatus(e) === 404) void refreshConversation(id);
  }
}

function onEdit(m: Message) {
  replyTarget.value = null;
  editTarget.value = m;
}

async function saveEdit({ message, body }: { message: Message; body: string }) {
  try {
    const fresh = await chatService.edit(message.id, body);
    if (fresh.conversation_id !== activeId.value) return;
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
    // New to this list: only when it belongs to the folder being shown.
    else if (inFolder(fresh)) conversations.value.unshift(fresh);
  } catch (e) {
    // Removed from it, or it is gone. A network blip changes nothing.
    const status = httpStatus(e);
    if (status !== 403 && status !== 404) return;
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

async function setMute(minutes: number, id = activeId.value) {
  showMuteMenu.value = false;
  try {
    await chatService.mute(id, minutes);
    await refreshConversation(id);
    void chatUnread.refresh();
  } catch (e) {
    toasts.error(e);
  }
}

async function toggleArchive(id = activeId.value) {
  const c = findConversation(id);
  showConversationMenu.value = false;
  if (!c) return;
  try {
    const fresh = await chatService.archive(c.id, !c.archived);
    // It leaves the folder being shown, but stays open.
    conversations.value = conversations.value.filter((x) => x.id !== c.id);
    if (c.id === activeId.value) opened.value = fresh;
    void chatUnread.refresh();
  } catch (e) {
    toasts.error(e);
  }
}

async function clearChat(id = activeId.value) {
  showConversationMenu.value = false;
  if (!id || !window.confirm(t("messages.clearConfirm"))) return;
  try {
    await chatService.clear(id);
    if (id === activeId.value) {
      messages.value = [];
      hasOlder.value = false;
      olderCursor.value = null;
    }
    const conversation = findConversation(id);
    if (conversation) conversation.unread_count = 0;
    void chatUnread.refresh();
  } catch (e) {
    toasts.error(e);
  }
}

function peerOf(c: Conversation | undefined | null): string {
  if (!c || c.type !== "dm") return "";
  return c.members.find((m) => m !== myId.value) ?? "";
}

/** Block the other person of a DM: graph applies it everywhere, chat closes the thread.
 *  It asks first, in the same dialog the post and profile menus use. */
const pendingBlock = ref<{ id: string; peer: string; name: string } | null>(null);
const blockBusy = ref(false);
function blockPeer(id = activeId.value) {
  const peer = peerOf(findConversation(id));
  showConversationMenu.value = false;
  if (!peer) return;
  pendingBlock.value = { id, peer, name: directory.label(peer) };
}
async function confirmBlockPeer() {
  const pending = pendingBlock.value;
  if (!pending || blockBusy.value) return;
  blockBusy.value = true;
  try {
    await relationshipPrefs.set("blocks", pending.peer, true);
    toasts.success(t("messenger.blocked", { name: pending.name }));
    pendingBlock.value = null;
    conversations.value = conversations.value.filter((c) => c.id !== pending.id);
    if (pending.id === activeId.value) router.push({ path: "/messages", query: route.query });
  } catch (e) {
    toasts.error(e);
  } finally {
    blockBusy.value = false;
  }
}

function reportPeer(id = activeId.value) {
  const peer = peerOf(findConversation(id));
  showConversationMenu.value = false;
  if (peer) reportPerson.value = { id: peer, name: directory.label(peer) };
}

/** Accept or decline a message request (row menu or the banner above the composer). */
async function answerRequest(action: "accept" | "decline", id = activeId.value) {
  try {
    const fresh = await chatService.answerRequest(id, action);
    toasts.success(action === "accept" ? t("messenger.request.accepted") : t("messenger.request.declined"));
    const index = conversations.value.findIndex((c) => c.id === id);
    if (inFolder(fresh)) {
      if (index >= 0) conversations.value[index] = fresh;
      else conversations.value = [fresh, ...conversations.value];
    } else {
      conversations.value = conversations.value.filter((c) => c.id !== id);
      if (id === activeId.value) opened.value = fresh;
    }
    void chatUnread.refresh();
  } catch (e) {
    toasts.error(e);
  }
}

function onRowAction(id: string, action: RowAction, minutes?: number) {
  if (action === "mute") void setMute(minutes ?? 480, id);
  else if (action === "unmute") void setMute(0, id);
  else if (action === "archive" || action === "unarchive") void toggleArchive(id);
  else if (action === "clear") void clearChat(id);
  else if (action === "block") blockPeer(id);
  else if (action === "report") reportPeer(id);
  else if (action === "accept" || action === "decline") void answerRequest(action, id);
}

function onNewConversation(conversation: Conversation) {
  showNewMessage.value = false;
  if (folder.value === "inbox" && !conversations.value.some((c) => c.id === conversation.id)) {
    conversations.value = [conversation, ...conversations.value];
  }
  router.push(`/messages/${conversation.id}`);
}

// Group "Seen by": the avatars of members whose last read message is this one.
const seenBy = computed(() =>
  isGroup.value ? seenByAt(messages.value, activeConversation.value?.member_states ?? [], myId.value) : {},
);
function seenNames(ids: string[]): string {
  const names = ids.map((id) => directory.label(id));
  try {
    return new Intl.ListFormat(locale.value, { style: "short", type: "conjunction" }).format(names);
  } catch {
    return names.join(", ");
  }
}
const requestState = computed(() => {
  const r = activeConversation.value?.request_status;
  return r === "pending" || r === "spam" ? r : "";
});

/** Scroll to a message, paging back through history if it isn't loaded yet. */
async function jumpTo(messageId: string) {
  const generation = loadGeneration;
  for (let i = 0; i <= MAX_JUMP_PAGES && generation === loadGeneration; i++) {
    await nextTick();
    const el = scroller.value?.querySelector(`[data-message-id="${messageId}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (!hasOlder.value || i === MAX_JUMP_PAGES) return;
    if (!(await loadOlder()) && !loadingOlder.value) return;
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
  return pin.body || typePreview(pin.type, t);
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
  if (!c || (folder.value !== "inbox" && !conversations.value.includes(c))) {
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
  document.addEventListener("visibilitychange", onVisible);
  loadConversations();
  loadMessages(activeId.value);
  subscribe(activeId.value);
  if (activeId.value) void calls.watchConversation(activeId.value);

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

function onVisible() {
  if (document.visibilityState === "visible" && atBottom.value) markLatestRead();
}

onUnmounted(() => {
  paneObserver?.disconnect();
  document.removeEventListener("visibilitychange", onVisible);
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
  if (id) void calls.watchConversation(id);
});
</script>

<template>
  <AppShell :right="false">
    <div
      class="card relative grid h-[calc(100vh-7rem)] grid-cols-1 grid-rows-[minmax(0,1fr)] overflow-hidden md:grid-cols-[320px_1fr]"
      :class="showInfo && activeId && activeConversation ? 'xl:grid-cols-[320px_minmax(0,1fr)_300px]' : ''"
    >
      <!-- Conversation list -->
      <div
        class="flex min-h-0 flex-col border-e border-gray-200 dark:border-gray-800"
        :class="activeId ? 'hidden md:flex' : 'flex'"
      >
        <div class="flex items-center justify-between px-4 pb-1 pt-3">
          <h2 class="text-2xl font-bold">{{ t("messages.title") }}</h2>
          <div class="flex items-center gap-0.5">
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
            <button
              class="btn-ghost px-2"
              :aria-label="t('messenger.newMessage')"
              :title="t('messenger.newMessage')"
              data-testid="messages-new"
              @click="showNewMessage = true"
            >
              <PenSquare class="h-5 w-5" />
            </button>
          </div>
        </div>
        <ChatSearch v-if="searchingAll" class="min-h-0 flex-1" :name-of="nameOf" :initial-query="initialSearch" @open="openSearchResult" />
        <template v-else>
          <!-- Chats, Requests and Marketplace always fit the 320px column; Archived
               and Spam sit behind "More" (shown as a chip while one is open). -->
          <div class="flex items-center gap-1 px-2 py-2">
            <div class="flex min-w-0 gap-0.5 overflow-x-auto [scrollbar-width:none]" role="tablist" :aria-label="t('messenger.folders.label')">
              <button
                v-for="f in visibleFolders"
                :key="f"
                role="tab"
                :aria-selected="folder === f"
                class="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-semibold"
                :class="folder === f ? 'bg-brand-50 text-brand-700 dark:bg-brand-950/60 dark:text-brand-200' : 'text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-800'"
                :data-testid="`folder-${f}`"
                @click="setFolder(f)"
              >
                <!-- Text-only chips (as the reference): with icons the three never fit 320px. -->
                {{ f === "requests" ? t("messenger.folders.requestsShort") : t(`messenger.folders.${f}`) }}
                <span v-if="f === 'requests' && chatUnread.requests > 0" class="badge">{{ chatUnread.requests }}</span>
              </button>
            </div>
            <div class="relative ms-auto shrink-0">
              <button
                type="button"
                class="flex h-8 w-8 items-center justify-center rounded-full text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-800"
                :aria-label="t('messenger.folders.more')"
                :title="t('messenger.folders.more')"
                aria-haspopup="menu"
                :aria-expanded="folderMenuOpen"
                data-testid="folder-more"
                @click="folderMenuOpen = !folderMenuOpen"
              >
                <MoreHorizontal class="h-4 w-4" />
              </button>
              <template v-if="folderMenuOpen">
                <div class="fixed inset-0 z-40" @click="folderMenuOpen = false" />
                <div class="popover absolute end-0 z-50 mt-1 w-56 p-1" role="menu">
                  <button
                    v-for="f in MORE_FOLDERS"
                    :key="f"
                    type="button"
                    role="menuitem"
                    class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-start text-sm hover:bg-gray-100 dark:hover:bg-gray-800"
                    :data-testid="`folder-menu-${f}`"
                    @click="folderMenuOpen = false; setFolder(f)"
                  >
                    <Archive v-if="f === 'archived'" class="h-4 w-4" aria-hidden="true" />
                    <ShieldAlert v-else class="h-4 w-4" aria-hidden="true" />
                    {{ t(`messenger.folders.${f}`) }}
                  </button>
                </div>
              </template>
            </div>
          </div>
          <p v-if="folder === 'requests' || folder === 'spam' || folder === 'marketplace'" class="px-4 pb-2 text-xs text-gray-500 dark:text-gray-400" data-testid="folder-hint">
            {{ t(`messenger.hints.${folder}`) }}
          </p>
          <div class="min-h-0 flex-1 overflow-y-auto">
            <LoadingSkeleton v-if="loadingList" :rows="4" />
            <ErrorState v-else-if="listError" @retry="loadConversations()" />
            <EmptyState v-else-if="conversations.length === 0">
              {{ folder === "archived" ? t("messages.noArchived") : folder === "inbox" ? t("messages.noConversations") : t(`messenger.empty.${folder}`) }}
            </EmptyState>
            <ConversationList
              v-else
              :conversations="conversations"
              :active-id="activeId"
              :self-id="myId"
              @select="select"
              @action="onRowAction"
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
              <span v-if="titlePending" class="block h-4 w-32 animate-pulse rounded bg-gray-200 dark:bg-gray-700" data-testid="conversation-title-skeleton" />
              <span v-else class="block truncate text-sm font-semibold" dir="auto" data-testid="conversation-title">{{ activeTitle }}</span>
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
              <CallButtons v-if="!isTeamThread(activeConversation)" :conversation-id="activeId" :conversation-type="activeConversation?.type" />
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
                  :aria-haspopup="activeConversation?.muted_until ? undefined : 'menu'"
                  :aria-expanded="activeConversation?.muted_until ? undefined : showMuteMenu"
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
              <button
                class="btn-ghost px-2"
                :class="showInfo ? 'text-brand-600 dark:text-brand-300' : ''"
                :aria-label="t('messenger.info.open')"
                :title="t('messenger.info.open')"
                :aria-pressed="showInfo"
                data-testid="conversation-info-toggle"
                @click="showInfo = !showInfo"
              >
                <Info class="h-5 w-5" />
              </button>
              <!-- Groups: members and roles (GroupPanel) -->
              <button v-if="isGroup" class="btn-ghost px-2" :aria-label="t('messages.groupInfo')" :title="t('messages.groupInfo')" @click="showGroupPanel = true">
                <Users class="h-5 w-5" />
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
                    <button class="block w-full rounded-lg px-3 py-2 text-start text-sm hover:bg-gray-100 dark:hover:bg-gray-800" role="menuitem" @click="toggleArchive()">
                      {{ activeConversation?.archived ? t("messages.unarchive") : t("messages.archive") }}
                    </button>
                    <button class="block w-full rounded-lg px-3 py-2 text-start text-sm text-red-600 hover:bg-gray-100 dark:hover:bg-gray-800" role="menuitem" @click="clearChat()">
                      {{ t("messages.clearChat") }}
                    </button>
                    <template v-if="activeConversation?.type === 'dm' && activePeerId">
                      <button class="block w-full rounded-lg px-3 py-2 text-start text-sm hover:bg-gray-100 dark:hover:bg-gray-800" role="menuitem" data-testid="conversation-block" @click="blockPeer()">
                        {{ titlePending ? t("messenger.blockNoName") : t("messenger.block", { name: activeTitle }) }}
                      </button>
                      <button class="block w-full rounded-lg px-3 py-2 text-start text-sm text-red-600 hover:bg-gray-100 dark:hover:bg-gray-800" role="menuitem" data-testid="conversation-report" @click="reportPeer()">
                        {{ titlePending ? t("messenger.reportNoName") : t("messenger.report", { name: activeTitle }) }}
                      </button>
                    </template>
                  </div>
                </template>
              </div>
            </div>
          </header>

          <CallBanner :conversation-id="activeId" />
          <ListingStrip
            v-if="activeConversation?.type === 'marketplace' && activeConversation.listing_id"
            :listing-id="activeConversation.listing_id"
          />

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
                <CallLogChip
                  v-else-if="row.message.type === 'system'"
                  :data-message-id="row.message.id"
                  :message="row.message"
                  :self-id="myId"
                  :conversation-id="activeId"
                  :callable="activeConversation?.type !== 'support' && activeConversation?.type !== 'page'"
                />
                <template v-else>
                <MessageBubble
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
                  :can-report="true"
                  @reply="onReply"
                  @react="onReact"
                  @pin="onPin"
                  @edit="onEdit"
                  @forward="forwardTarget = $event"
                  @delete="onDelete"
                  @report="reportTarget = $event"
                />
                <div
                  v-if="seenBy[row.message.id]?.length"
                  class="flex justify-end gap-0.5 pe-1"
                  :title="t('messenger.seenBy', { names: seenNames(seenBy[row.message.id]) })"
                  :aria-label="t('messenger.seenBy', { names: seenNames(seenBy[row.message.id]) })"
                  role="img"
                  data-testid="seen-by"
                >
                  <UserAvatar
                    v-for="id in seenBy[row.message.id].slice(0, 6)"
                    :key="id"
                    :name="directory.label(id)"
                    :media-id="directory.avatarOf(id)"
                    :size="14"
                  />
                  <span v-if="seenBy[row.message.id].length > 6" class="text-[10px] text-gray-500">+{{ seenBy[row.message.id].length - 6 }}</span>
                </div>
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

          <!-- A Page or Tara Support thread: the team answers as the Page / as Tara Support -->
          <p
            v-if="isTeamThread(activeConversation)"
            class="border-t border-gray-200 bg-gray-50 px-4 py-2 text-center text-xs text-gray-500 dark:border-gray-800 dark:bg-gray-900/60 dark:text-gray-400"
            data-testid="team-thread-hint"
          >
            {{ t("chatTeam.teamThreadHint", { name: activeTitle }) }}
          </p>
          <!-- Message request: accept to move it to the inbox, delete (spam) or block -->
          <div
            v-if="requestState"
            class="border-t border-gray-200 bg-gray-50 px-4 py-3 text-center dark:border-gray-800 dark:bg-gray-900/60"
            data-testid="request-banner"
          >
            <p class="text-sm font-semibold" dir="auto">
              {{ requestState === "pending" ? t("messenger.request.title", { name: activeTitle }) : t("messenger.request.spamTitle") }}
            </p>
            <p class="mx-auto mt-0.5 max-w-md text-xs text-gray-500 dark:text-gray-400" dir="auto">
              {{ requestState === "pending" ? t("messenger.request.hint", { name: activeTitle }) : t("messenger.request.spamHint", { name: activeTitle }) }}
            </p>
            <div class="mt-2 flex justify-center gap-2">
              <button v-if="activePeerId" class="btn-ghost px-3 py-1.5 text-sm" data-testid="request-block" @click="blockPeer()">{{ t("messenger.request.block") }}</button>
              <button v-if="requestState === 'pending'" class="btn-outline px-3 py-1.5 text-sm" data-testid="request-decline" @click="answerRequest('decline')">
                {{ t("messenger.request.decline") }}
              </button>
              <button class="btn-primary px-3 py-1.5 text-sm" data-testid="request-accept" @click="answerRequest('accept')">{{ t("messenger.request.accept") }}</button>
            </div>
          </div>

          <MessageComposer
            :key="activeId"
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

      <!-- Third column (xl+), a drawer over the chat below that -->
      <div
        v-if="showInfo && activeId && activeConversation"
        class="absolute inset-y-0 end-0 z-30 w-full border-s border-gray-200 shadow-pop dark:border-gray-800 sm:w-80 xl:static xl:z-auto xl:w-auto xl:shadow-none"
      >
        <ConversationInfoPanel
          :conversation="activeConversation"
          :self-id="myId"
          :title="activeTitle"
          :name-of="nameOf"
          @close="showInfo = false"
          @jump="jumpTo"
          @open-result="openSearchResult"
          @mute="setMute"
          @archive="toggleArchive()"
          @clear="clearChat()"
          @block="blockPeer()"
          @report="reportPeer()"
          @manage-group="showGroupPanel = true"
        />
      </div>
    </div>

    <ConfirmActionDialog
      v-if="pendingBlock"
      :title="t('people.actions.blockTitle', { name: pendingBlock.name })"
      :hint="t('people.actions.blockHint')"
      :confirm-label="t('people.actions.block')"
      :busy="blockBusy"
      @confirm="confirmBlockPeer"
      @cancel="pendingBlock = null"
    />
    <NewMessageModal v-if="showNewMessage" @close="showNewMessage = false" @done="onNewConversation" />
    <ReportDialog
      v-if="reportPerson"
      target-type="user"
      :target-id="reportPerson.id"
      :name="reportPerson.name"
      @close="reportPerson = null"
    />
    <MessageReportDialog v-if="reportTarget" :message="reportTarget" @close="reportTarget = null" />

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
