<script setup lang="ts">
import { Search } from "lucide-vue-next";
import { onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { relativeTime } from "@/lib/format";
import { chatService } from "@/services/chat";
import type { CursorPage, Message } from "@/types";

// Message search. With `conversationId` it searches one conversation,
// otherwise every conversation the viewer belongs to. Matching is done on the
// server (Arabic-normalised, so "احمد" finds "أحمد").
const props = defineProps<{ conversationId?: string; nameOf: (id: string) => string }>();
const emit = defineEmits<{ open: [message: Message] }>();
const { t } = useI18n();

const query = ref("");
const results = ref<Message[]>([]);
const next = ref<string | null>(null);
const loading = ref(false);
const searched = ref(false);
const tooShort = ref(false);
let timer: number | null = null;
let generation = 0;

async function run(cursor?: string) {
  const q = query.value.trim();
  tooShort.value = q.length > 0 && q.length < 2;
  if (q.length < 2) {
    results.value = [];
    searched.value = false;
    return;
  }
  const mine = ++generation;
  loading.value = true;
  try {
    const page: CursorPage<Message> = props.conversationId
      ? await chatService.searchIn(props.conversationId, q, cursor)
      : await chatService.search(q, cursor);
    if (mine !== generation) return;
    results.value = cursor ? [...results.value, ...page.data] : page.data;
    next.value = page.page.has_more ? page.page.next_cursor : null;
    searched.value = true;
  } catch {
    if (mine === generation) results.value = cursor ? results.value : [];
  } finally {
    if (mine === generation) loading.value = false;
  }
}

watch(query, () => {
  if (timer) window.clearTimeout(timer);
  timer = window.setTimeout(() => void run(), 300);
});
watch(
  () => props.conversationId,
  () => void run(),
);
onBeforeUnmount(() => {
  if (timer) window.clearTimeout(timer);
});
</script>

<template>
  <div class="flex min-h-0 flex-col" data-testid="chat-search">
    <label class="relative block p-2">
      <Search class="pointer-events-none absolute start-4 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
      <input
        v-model="query"
        type="search"
        class="input ps-8"
        dir="auto"
        :placeholder="t('messages.searchPlaceholder')"
        :aria-label="conversationId ? t('messages.search') : t('messages.searchAll')"
      />
    </label>
    <p v-if="tooShort" class="px-3 text-xs text-gray-500 dark:text-gray-400">{{ t("messages.searchTooShort") }}</p>
    <p v-else-if="searched && !loading && !results.length" class="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">
      {{ t("messages.noResults") }}
    </p>
    <ul class="min-h-0 flex-1 divide-y divide-gray-100 overflow-y-auto dark:divide-gray-800">
      <li v-for="m in results" :key="m.id">
        <button class="block w-full px-3 py-2 text-start hover:bg-gray-50 dark:hover:bg-gray-800/50" @click="emit('open', m)">
          <span class="flex items-center justify-between gap-2 text-xs text-gray-500 dark:text-gray-400">
            <span class="truncate font-semibold" dir="auto">{{ nameOf(m.sender_id) }}</span>
            <time class="shrink-0">{{ relativeTime(m.created_at) }}</time>
          </span>
          <span class="line-clamp-2 block text-sm" dir="auto">{{ m.body }}</span>
        </button>
      </li>
    </ul>
    <button v-if="next && !loading" class="btn-ghost m-2 justify-center text-sm" @click="run(next ?? undefined)">
      {{ t("messages.loadMore") }}
    </button>
    <p v-if="loading" class="py-2 text-center text-xs text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
  </div>
</template>
