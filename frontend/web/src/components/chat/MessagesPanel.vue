<script setup lang="ts">
// The top-bar Messenger dropdown's list: the newest chats with their last
// message, paged with "Load more", and an "Unread" filter answered by the
// server (unread=1), so unread chats beyond the first page are not missed.
import { BellOff, Store } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { badgeText, conversationTitle, isTeamThread, teamThreadTitle } from "@/lib/chat";
import { relativeTime } from "@/lib/format";
import { chatService } from "@/services/chat";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";
import type { Conversation } from "@/types";

import ListingAvatar from "./ListingAvatar.vue";
import MessagePreview from "./MessagePreview.vue";

const props = withDefaults(defineProps<{ limit?: number; unread?: boolean }>(), { limit: 8, unread: false });
const emit = defineEmits<{ navigate: [] }>();

const { t, locale } = useI18n();
const auth = useAuthStore();
const directory = useDirectoryStore();
const presence = usePresenceStore();
const items = ref<Conversation[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
let generation = 0;

async function load() {
  const mine = ++generation;
  loading.value = true;
  error.value = false;
  try {
    const page = await chatService.folderPage({ unread: props.unread });
    if (mine !== generation) return;
    items.value = page.data.slice(0, props.limit);
    cursor.value = page.page.has_more ? page.page.next_cursor : null;
    overflow.value = page.data.slice(props.limit);
  } catch {
    if (mine === generation) error.value = true;
  } finally {
    if (mine === generation) loading.value = false;
  }
}

// Rows of the first page beyond `limit`, shown before fetching the next page.
const overflow = ref<Conversation[]>([]);
async function loadMore() {
  if (loadingMore.value) return;
  if (overflow.value.length) {
    items.value = [...items.value, ...overflow.value];
    overflow.value = [];
    return;
  }
  if (!cursor.value) return;
  const mine = generation;
  loadingMore.value = true;
  try {
    const page = await chatService.folderPage({ cursor: cursor.value, unread: props.unread });
    if (mine !== generation) return;
    const known = new Set(items.value.map((c) => c.id));
    items.value = [...items.value, ...page.data.filter((c) => !known.has(c.id))];
    cursor.value = page.page.has_more ? page.page.next_cursor : null;
  } catch {
    // The button stays; the next click retries.
  } finally {
    loadingMore.value = false;
  }
}

function isDm(c: Conversation): boolean {
  return c.type !== "group" && !isTeamThread(c) && c.members.length <= 2;
}
function peerId(c: Conversation): string | undefined {
  return c.members.find((m) => m !== auth.account?.id);
}
function title(c: Conversation): string {
  if (isTeamThread(c)) return teamThreadTitle(c, t);
  if (!c.title && isDm(c) && peerId(c)) return directory.label(peerId(c));
  return conversationTitle(c, auth.account?.id, directory.label, locale.value, t("messages.groupFallback"));
}

watch(() => props.unread, load);
onMounted(load);
defineExpose({ reload: load });
</script>

<template>
  <div class="min-h-24">
    <LoadingSkeleton v-if="loading" :rows="3" />
    <ErrorState v-else-if="error" @retry="load" />
    <EmptyState v-else-if="items.length === 0">
      {{ unread ? t("messenger.empty.unread") : t("messages.noConversations") }}
    </EmptyState>
    <template v-else>
      <ul class="space-y-0.5" data-testid="messenger-dropdown-list">
        <li v-for="c in items" :key="c.id">
          <RouterLink
            :to="`/messages/${c.id}`"
            class="flex items-center gap-3 rounded-xl px-2 py-2 transition hover:bg-gray-100 dark:hover:bg-gray-800"
            data-testid="messenger-dropdown-row"
            @click="emit('navigate')"
          >
            <span class="relative shrink-0">
              <ListingAvatar
                v-if="c.type === 'marketplace' && c.listing_title"
                :cover-media-id="c.listing_cover_media_id"
                :name="title(c)"
                :peer-media-id="peerId(c) ? directory.avatarOf(peerId(c)!) : null"
              />
              <UserAvatar v-else :name="title(c)" :media-id="isDm(c) ? directory.avatarOf(peerId(c)) : null" :size="48" />
              <span
                v-if="isDm(c) && peerId(c) && presence.isOnline(peerId(c)!) && !(c.type === 'marketplace' && c.listing_title)"
                class="absolute -bottom-0.5 -end-0.5 h-3.5 w-3.5 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
                :title="t('presence.online')"
              />
            </span>
            <span class="min-w-0 flex-1">
              <span class="flex min-w-0 items-center gap-1">
                <span class="truncate text-sm" :class="[c.unread_count ? 'font-bold' : 'font-medium', c.type === 'marketplace' && c.listing_title ? 'max-w-[55%] shrink-0' : '']" dir="auto">{{ title(c) }}</span>
                <template v-if="c.type === 'marketplace' && c.listing_title">
                  <span class="shrink-0 text-sm text-gray-500 dark:text-gray-400" aria-hidden="true">·</span>
                  <span class="min-w-0 truncate text-sm text-accent-700 dark:text-accent-300" dir="auto" data-testid="conversation-listing">{{ c.listing_title }}</span>
                </template>
                <Store v-else-if="c.type === 'marketplace'" class="h-3.5 w-3.5 shrink-0 text-accent-600 dark:text-accent-300" :aria-label="t('messenger.marketplaceBadge')" />
              </span>
              <span class="flex items-center gap-1 text-xs" :class="c.unread_count ? 'font-semibold text-gray-900 dark:text-white' : 'text-gray-500 dark:text-gray-400'">
                <MessagePreview :conversation="c" :self-id="auth.account?.id" :fallback="c.type === 'group' ? t('messages.membersCount', c.members.length) : ''" />
                <template v-if="c.last_message_at">
                  <span aria-hidden="true">·</span>
                  <time class="shrink-0">{{ relativeTime(c.last_message_at) }}</time>
                </template>
              </span>
            </span>
            <BellOff v-if="c.muted_until" class="h-3.5 w-3.5 shrink-0 text-gray-400" :aria-label="t('messages.muted')" />
            <span v-if="c.unread_count" class="badge shrink-0" :aria-label="t('messages.unreadCount', c.unread_count)">
              {{ badgeText(c.unread_count) }}
            </span>
          </RouterLink>
        </li>
      </ul>
      <button
        v-if="cursor || overflow.length"
        type="button"
        class="btn-ghost mt-1 w-full text-sm"
        :disabled="loadingMore"
        data-testid="messenger-dropdown-more"
        @click="loadMore"
      >
        {{ loadingMore ? t("states.loading") : t("messenger.loadMore") }}
      </button>
    </template>
  </div>
</template>
