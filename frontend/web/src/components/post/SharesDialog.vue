<script setup lang="ts">
import { X } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { relativeTime } from "@/lib/format";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { type Sharer, postService } from "@/services/post";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

// Who shared a post. Only shares this viewer could open are listed, so the
// list can be shorter than the share count.
const props = defineProps<{ postId: string }>();
const emit = defineEmits<{ close: [] }>();

const { t } = useI18n();
const directory = useDirectoryStore();
const toasts = useToastStore();
useEscapeKey(ref(true), () => emit("close"));
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);

const items = ref<Sharer[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(false);

async function load() {
  if (loading.value) return;
  loading.value = true;
  try {
    const page = await postService.shares(props.postId, cursor.value);
    items.value = items.value.concat(page.data);
    cursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 p-0 backdrop-blur-sm sm:items-center sm:p-4">
    <div class="fixed inset-0" @click="emit('close')" />
    <div
      ref="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="shares-dialog-title"
      tabindex="-1"
      class="card relative z-10 flex max-h-[80vh] w-full animate-pop-in flex-col rounded-b-none rounded-t-2xl p-4 shadow-pop sm:max-w-md sm:rounded-2xl sm:p-5"
    >
      <div class="mb-3 flex items-center justify-between">
        <h2 id="shares-dialog-title" class="text-lg font-bold">{{ t("post.sharesTitle") }}</h2>
        <button class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('post.viewer.close')" @click="emit('close')">
          <X class="h-5 w-5" />
        </button>
      </div>

      <ul class="-mx-1 min-h-24 flex-1 space-y-1 overflow-y-auto">
        <li v-for="s in items" :key="s.share_post_id">
          <RouterLink
            :to="`/posts/${s.share_post_id}`"
            class="flex items-start gap-3 rounded-xl px-2 py-1.5 transition hover:bg-gray-100 dark:hover:bg-gray-800"
            :aria-label="`${directory.label(s.account_id)} · ${t('post.viewShare')}`"
            @click="emit('close')"
          >
            <UserAvatar :name="directory.label(s.account_id)" :media-id="directory.avatarOf(s.account_id)" :size="40" />
            <span class="min-w-0">
              <span class="block truncate text-sm font-semibold" dir="auto">{{ directory.label(s.account_id) }}</span>
              <span v-if="s.body" class="line-clamp-2 block text-sm text-gray-600 dark:text-gray-300" dir="auto">{{ s.body }}</span>
              <time class="block text-xs text-gray-500 dark:text-gray-400">{{ relativeTime(s.created_at) }}</time>
            </span>
          </RouterLink>
        </li>
        <li v-if="loading" class="px-2 py-2 text-xs text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</li>
        <li v-else-if="!items.length" class="px-2 py-2 text-sm text-gray-500 dark:text-gray-400">{{ t("post.noShares") }}</li>
      </ul>

      <button v-if="cursor && !loading" class="btn-ghost mt-2 w-full" @click="load">
        {{ t("feed.loadMore") }}
      </button>
    </div>
  </div>
</template>
