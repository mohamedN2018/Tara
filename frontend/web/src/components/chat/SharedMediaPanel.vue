<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import ChatAttachment from "@/components/chat/ChatAttachment.vue";
import VoicePlayer from "@/components/chat/VoicePlayer.vue";
import { relativeTime } from "@/lib/format";
import { chatService, type SharedMediaItem } from "@/services/chat";

// Images, videos, voice notes and files shared in one conversation, newest
// first, a page at a time. Every item's URL is minted by chat on demand.
const props = defineProps<{ conversationId: string }>();
const emit = defineEmits<{ jump: [messageId: string] }>();
const { t } = useI18n();

const TABS = [
  { kind: "image", label: "messages.mediaPhotos" },
  { kind: "video", label: "messages.mediaVideos" },
  { kind: "voice", label: "messages.mediaVoice" },
  { kind: "file", label: "messages.mediaFiles" },
] as const;

const kind = ref<string>("image");
const items = ref<SharedMediaItem[]>([]);
const next = ref<string | null>(null);
const loading = ref(false);
const failed = ref(false);

async function load(cursor?: string) {
  loading.value = true;
  failed.value = false;
  const wanted = kind.value;
  try {
    const page = await chatService.sharedMedia(props.conversationId, wanted, cursor);
    if (wanted !== kind.value) return;
    items.value = cursor ? [...items.value, ...page.data] : page.data;
    next.value = page.page.has_more ? page.page.next_cursor : null;
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

function choose(k: string) {
  if (k === kind.value) return;
  kind.value = k;
  items.value = [];
  next.value = null;
  void load();
}

onMounted(() => void load());
</script>

<template>
  <div class="flex min-h-0 flex-col" data-testid="shared-media">
    <div class="flex gap-1 border-b border-gray-200 p-2 dark:border-gray-800" role="tablist">
      <button
        v-for="tab in TABS"
        :key="tab.kind"
        role="tab"
        :aria-selected="kind === tab.kind"
        class="rounded-full px-3 py-1 text-xs font-medium"
        :class="kind === tab.kind ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200'"
        @click="choose(tab.kind)"
      >
        {{ t(tab.label) }}
      </button>
    </div>
    <div class="min-h-0 flex-1 overflow-y-auto p-2">
      <p v-if="!loading && !failed && !items.length" class="py-4 text-center text-sm text-gray-500 dark:text-gray-400">
        {{ t("messages.noMedia") }}
      </p>
      <p v-if="failed" class="py-4 text-center text-sm text-red-600">{{ t("states.error") }}</p>
      <div v-if="kind === 'image' || kind === 'video'" class="grid grid-cols-3 gap-1">
        <button
          v-for="item in items"
          :key="item.id"
          class="overflow-hidden rounded-md"
          :aria-label="relativeTime(item.created_at)"
          @click="emit('jump', item.message_id)"
        >
          <ChatAttachment :message-id="item.message_id" :attachment="item" compact />
        </button>
      </div>
      <ul v-else class="space-y-2">
        <li v-for="item in items" :key="item.id" class="rounded-lg bg-gray-50 p-2 dark:bg-gray-800/50">
          <VoicePlayer v-if="kind === 'voice'" :media-id="item.media_id" :message-id="item.message_id" :duration-ms="item.duration_ms" />
          <ChatAttachment v-else :message-id="item.message_id" :attachment="item" />
          <button class="mt-1 text-[11px] text-gray-500 hover:underline dark:text-gray-400" @click="emit('jump', item.message_id)">
            {{ relativeTime(item.created_at) }}
          </button>
        </li>
      </ul>
      <button v-if="next && !loading" class="btn-ghost mt-2 w-full justify-center text-sm" @click="load(next ?? undefined)">
        {{ t("messages.loadMore") }}
      </button>
      <p v-if="loading" class="py-2 text-center text-xs text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
    </div>
  </div>
</template>
