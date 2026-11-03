<script setup lang="ts">
import { X } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { reactionByKey } from "@/lib/reactions";
import { topReactions } from "@/lib/reactionCounts";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { type Reactor, postService } from "@/services/post";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

// Who reacted to a post, with a tab per reaction type. The server leaves out
// accounts blocked either way and 404s when the post is no longer visible.
const props = defineProps<{ postId: string; counts: Record<string, number>; total: number }>();
const emit = defineEmits<{ close: [] }>();

const { t } = useI18n();
const directory = useDirectoryStore();
const toasts = useToastStore();
useEscapeKey(ref(true), () => emit("close"));
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);

const tabs = computed(() => topReactions(props.counts, 7));
const active = ref<string | null>(null);
const items = ref<Reactor[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(false);

async function load(reset: boolean) {
  if (loading.value) return;
  loading.value = true;
  try {
    const page = await postService.reactions(props.postId, active.value, reset ? null : cursor.value);
    items.value = reset ? page.data : items.value.concat(page.data);
    cursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    loading.value = false;
  }
}

function pick(type: string | null) {
  if (active.value === type) return;
  active.value = type;
  items.value = [];
  cursor.value = null;
  load(true);
}

onMounted(() => load(true));
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 p-0 backdrop-blur-sm sm:items-center sm:p-4">
    <div class="fixed inset-0" @click="emit('close')" />
    <div
      ref="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="reactions-dialog-title"
      tabindex="-1"
      class="card relative z-10 flex max-h-[80vh] w-full animate-pop-in flex-col rounded-b-none rounded-t-2xl p-4 shadow-pop sm:max-w-md sm:rounded-2xl sm:p-5"
    >
      <div class="mb-3 flex items-center justify-between">
        <h2 id="reactions-dialog-title" class="text-lg font-bold">{{ t("post.reactionsTitle") }}</h2>
        <button class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('post.viewer.close')" @click="emit('close')">
          <X class="h-5 w-5" />
        </button>
      </div>

      <div class="mb-3 flex gap-1.5 overflow-x-auto pb-1" role="tablist" :aria-label="t('post.reactionsTitle')">
        <button
          role="tab"
          class="chip shrink-0"
          :class="active === null ? 'chip-active' : ''"
          :aria-selected="active === null"
          @click="pick(null)"
        >
          {{ t("post.reactionsAll") }} <span class="tabular-nums">{{ total }}</span>
        </button>
        <button
          v-for="type in tabs"
          :key="type"
          role="tab"
          class="chip shrink-0"
          :class="active === type ? 'chip-active' : ''"
          :aria-selected="active === type"
          :aria-label="`${t(reactionByKey(type)?.labelKey ?? 'post.like')} ${counts[type]}`"
          @click="pick(type)"
        >
          <span aria-hidden="true">{{ reactionByKey(type)?.emoji }}</span>
          <span class="tabular-nums">{{ counts[type] }}</span>
        </button>
      </div>

      <ul class="-mx-1 min-h-24 flex-1 space-y-1 overflow-y-auto" role="tabpanel">
        <li v-for="r in items" :key="r.account_id">
          <RouterLink
            :to="{ name: 'profile-by-id', params: { id: r.account_id } }"
            class="flex items-center gap-3 rounded-xl px-2 py-1.5 transition hover:bg-gray-100 dark:hover:bg-gray-800"
            @click="emit('close')"
          >
            <span class="relative">
              <UserAvatar :name="directory.label(r.account_id)" :media-id="directory.avatarOf(r.account_id)" :size="40" />
              <span class="absolute -bottom-1 -end-1 text-sm leading-none" aria-hidden="true">{{ reactionByKey(r.type)?.emoji }}</span>
            </span>
            <span class="min-w-0 truncate text-sm font-semibold" dir="auto">{{ directory.label(r.account_id) }}</span>
          </RouterLink>
        </li>
        <li v-if="loading" class="px-2 py-2 text-xs text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</li>
        <li v-else-if="!items.length" class="px-2 py-2 text-sm text-gray-500 dark:text-gray-400">{{ t("post.noReactions") }}</li>
      </ul>

      <button v-if="cursor && !loading" class="btn-ghost mt-2 w-full" @click="load(false)">
        {{ t("feed.loadMore") }}
      </button>
    </div>
  </div>
</template>
