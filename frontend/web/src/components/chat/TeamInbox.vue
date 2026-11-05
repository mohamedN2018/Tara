<script setup lang="ts">
// A team inbox: the people who wrote to a Page (`pageId`, for the page's team)
// or to Tara Support (no `pageId`, for the moderation team). The team answers
// as the Page / as Tara Support; the member never sees which teammate wrote,
// while the team sees it on each reply ("Answered by ..."). Every call is
// checked on the server (404 for anyone off the team). The list refreshes
// itself every 20 seconds while open: team threads have no live channel yet.
import { ArrowLeft, Inbox, RefreshCw, Send } from "lucide-vue-next";
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { teamSenderName } from "@/lib/chat";
import { relativeTime } from "@/lib/format";
import { chatService, type TeamConversation, type TeamMessage } from "@/services/chat";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

// `openId`: a thread to open on arrival (a notification's `?conversation=`).
const props = withDefaults(defineProps<{ pageId?: string; teamName: string; openId?: string }>(), { pageId: "", openId: "" });

const { t } = useI18n();
const directory = useDirectoryStore();
const toasts = useToastStore();

const rows = ref<TeamConversation[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);

const activeId = ref("");
const active = computed(() => rows.value.find((r) => r.id === activeId.value) ?? null);
const messages = ref<TeamMessage[]>([]);
const olderCursor = ref<string | null>(null);
const threadLoading = ref(false);
const threadError = ref(false);
const draft = ref("");
const sending = ref(false);
const scroller = ref<HTMLElement | null>(null);

async function load(silent = false) {
  if (!silent) {
    loading.value = true;
    error.value = false;
  }
  try {
    const page = await chatService.teamInbox(props.pageId || undefined);
    rows.value = page.data;
    cursor.value = page.page.has_more ? page.page.next_cursor : null;
  } catch {
    if (!silent) error.value = true;
  } finally {
    loading.value = false;
  }
}

async function loadMore() {
  if (!cursor.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await chatService.teamInbox(props.pageId || undefined, cursor.value);
    const seen = new Set(rows.value.map((r) => r.id));
    rows.value.push(...page.data.filter((r) => !seen.has(r.id)));
    cursor.value = page.page.has_more ? page.page.next_cursor : null;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

async function scrollToEnd() {
  await nextTick();
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight;
}

async function openThread(id: string) {
  activeId.value = id;
  messages.value = [];
  threadLoading.value = true;
  threadError.value = false;
  try {
    const page = await chatService.teamMessages(id);
    messages.value = page.data;
    olderCursor.value = page.page.has_more ? page.page.next_cursor : null;
    void scrollToEnd();
    await chatService.teamRead(id);
    const row = rows.value.find((r) => r.id === id);
    if (row) row.team_unread = 0;
  } catch {
    threadError.value = true;
  } finally {
    threadLoading.value = false;
  }
}

async function loadOlder() {
  if (!olderCursor.value || !activeId.value) return;
  try {
    const page = await chatService.teamMessages(activeId.value, olderCursor.value);
    messages.value = [...page.data, ...messages.value];
    olderCursor.value = page.page.has_more ? page.page.next_cursor : null;
  } catch (e) {
    toasts.error(e);
  }
}

async function send() {
  const body = draft.value.trim();
  if (!body || !activeId.value || sending.value) return;
  sending.value = true;
  try {
    const message = await chatService.teamReply(activeId.value, body);
    messages.value.push(message);
    draft.value = "";
    const row = rows.value.find((r) => r.id === activeId.value);
    if (row) {
      row.last_message = { id: message.id, sender_id: message.sender_id, type: message.type, body: message.body, deleted: false, created_at: message.created_at };
      row.last_message_at = message.created_at;
    }
    void scrollToEnd();
  } catch (e) {
    toasts.error(e);
  } finally {
    sending.value = false;
  }
}

/** Who wrote a message: the member, or the team (named as the Page / Tara Support). */
function senderOf(m: TeamMessage): string {
  if (!active.value) return "";
  return teamSenderName(active.value, m.sender_id, t) ?? directory.label(m.sender_id);
}
const fromTeam = (m: TeamMessage) => !!active.value && teamSenderName(active.value, m.sender_id, t) !== null;

let timer: number | undefined;
onMounted(async () => {
  await load();
  if (props.openId) void openThread(props.openId);
  timer = window.setInterval(() => {
    if (document.visibilityState === "visible") void load(true);
  }, 20_000);
});
onUnmounted(() => window.clearInterval(timer));
</script>

<template>
  <section class="card overflow-hidden md:grid md:h-[calc(100vh-13rem)] md:min-h-[28rem] md:grid-cols-[20rem_minmax(0,1fr)]" data-testid="team-inbox">
    <!-- The list -->
    <div class="flex min-h-0 flex-col border-gray-200 dark:border-gray-800 md:border-e" :class="activeId ? 'hidden md:flex' : 'flex'">
      <div class="flex items-center justify-between gap-2 px-4 pb-2 pt-3">
        <h2 class="truncate text-lg font-bold" data-testid="team-inbox-name"><bdi>{{ teamName }}</bdi></h2>
        <button type="button" class="icon-btn h-9 w-9" :aria-label="t('chatTeam.refresh')" :title="t('chatTeam.refresh')" data-testid="team-inbox-refresh" @click="load()">
          <RefreshCw class="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        <LoadingSkeleton v-if="loading" :rows="4" />
        <ErrorState v-else-if="error" @retry="load()" />
        <EmptyState v-else-if="!rows.length">
          <template #icon><Inbox class="h-8 w-8" /></template>
          {{ t("chatTeam.empty") }}
        </EmptyState>
        <ul v-else class="space-y-0.5">
          <li v-for="r in rows" :key="r.id">
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-xl p-2 text-start transition hover:bg-gray-100 dark:hover:bg-gray-800"
              :class="r.id === activeId ? 'bg-brand-50 dark:bg-brand-950/40' : ''"
              :aria-current="r.id === activeId ? 'true' : undefined"
              data-testid="team-row"
              @click="openThread(r.id)"
            >
              <UserAvatar :name="directory.label(r.account_id)" :media-id="directory.avatarOf(r.account_id)" :size="48" />
              <span class="min-w-0 flex-1">
                <span class="flex items-center gap-2">
                  <bdi class="truncate text-sm" :class="r.team_unread ? 'font-bold' : 'font-medium'">{{ directory.label(r.account_id) }}</bdi>
                  <time v-if="r.last_message_at" class="ms-auto shrink-0 text-xs text-gray-600 dark:text-gray-300" :datetime="r.last_message_at">{{ relativeTime(r.last_message_at) }}</time>
                </span>
                <span class="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
                  <span class="min-w-0 flex-1 truncate" dir="auto">{{ r.last_message?.deleted ? t("messages.deleted") : r.last_message?.body }}</span>
                  <span v-if="r.team_unread" class="badge shrink-0" data-testid="team-unread">{{ t("chatTeam.newCount", { count: r.team_unread }) }}</span>
                </span>
              </span>
            </button>
          </li>
        </ul>
        <button v-if="cursor" type="button" class="btn-ghost mx-auto mt-2 block text-sm" :disabled="loadingMore" @click="loadMore">
          {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
        </button>
      </div>
    </div>

    <!-- The thread -->
    <div class="min-h-[24rem] min-w-0 flex-col" :class="activeId ? 'flex' : 'hidden md:flex'">
      <p v-if="!active" class="m-auto p-6 text-sm text-gray-500 dark:text-gray-400">{{ t("chatTeam.choose") }}</p>
      <template v-else>
        <header class="flex items-center gap-3 border-b border-gray-200 px-3 py-2 dark:border-gray-800">
          <button type="button" class="icon-btn h-9 w-9 md:hidden" :aria-label="t('chatTeam.back')" @click="activeId = ''">
            <ArrowLeft class="h-5 w-5 rtl:rotate-180" aria-hidden="true" />
          </button>
          <UserAvatar :name="directory.label(active.account_id)" :media-id="directory.avatarOf(active.account_id)" :size="40" />
          <RouterLink v-if="active.account_id" :to="`/u/id/${active.account_id}`" class="min-w-0 truncate font-semibold hover:underline" data-testid="team-thread-member">
            <bdi>{{ directory.label(active.account_id) }}</bdi>
          </RouterLink>
        </header>
        <div ref="scroller" class="min-h-0 flex-1 space-y-2 overflow-y-auto p-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400" role="log" tabindex="0" :aria-label="directory.label(active.account_id)" data-testid="team-thread">
          <LoadingSkeleton v-if="threadLoading" :rows="3" />
          <ErrorState v-else-if="threadError" @retry="openThread(activeId)" />
          <template v-else>
            <button v-if="olderCursor" type="button" class="btn-ghost mx-auto block text-xs" @click="loadOlder">{{ t("feed.loadMore") }}</button>
            <div v-for="m in messages" :key="m.id" class="flex" :class="fromTeam(m) ? 'justify-end' : 'justify-start'" data-testid="team-message">
              <div class="max-w-[80%]">
                <p
                  class="whitespace-pre-wrap break-words rounded-2xl px-3 py-2 text-sm"
                  :class="fromTeam(m) ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-900 dark:bg-gray-800 dark:text-gray-100'"
                  dir="auto"
                >{{ m.deleted ? t("messages.deleted") : m.body }}</p>
                <p class="mt-0.5 px-1 text-[11px] text-gray-600 dark:text-gray-300" :class="fromTeam(m) ? 'text-end' : ''">
                  <bdi>{{ senderOf(m) }}</bdi>
                  <template v-if="fromTeam(m) && m.author_id"> · {{ t("chatTeam.answeredBy", { name: directory.label(m.author_id) }) }}</template>
                  · <time :datetime="m.created_at">{{ relativeTime(m.created_at) }}</time>
                </p>
              </div>
            </div>
          </template>
        </div>
        <p v-if="active.left" class="border-t border-gray-200 p-3 text-center text-sm text-gray-500 dark:border-gray-800 dark:text-gray-400" data-testid="team-left">{{ t("chatTeam.left") }}</p>
        <form v-else class="flex items-end gap-2 border-t border-gray-200 p-3 dark:border-gray-800" @submit.prevent="send">
          <label class="min-w-0 flex-1">
            <span class="sr-only">{{ t("chatTeam.replyAs", { name: teamName }) }}</span>
            <textarea
              v-model="draft"
              rows="1"
              maxlength="8000"
              class="input max-h-32 min-h-[2.5rem] resize-y rounded-2xl"
              dir="auto"
              :placeholder="t('chatTeam.replyAs', { name: teamName })"
              data-testid="team-reply"
              @keydown.enter.exact.prevent="send"
            />
          </label>
          <button type="submit" class="btn-primary h-10 shrink-0" :disabled="sending || !draft.trim()" data-testid="team-send">
            <Send class="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" /> {{ t("chatTeam.send") }}
          </button>
        </form>
      </template>
    </div>
  </section>
</template>
