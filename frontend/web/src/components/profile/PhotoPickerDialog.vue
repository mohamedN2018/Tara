<script setup lang="ts">
import { X } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { useMediaList } from "@/lib/useMediaList";
import { postService } from "@/services/post";

// "Choose from your photos" (plan 08): the photos of the account's own posts,
// newest first, from the post service (`?media=photo`). Picking one hands back
// its media id; the profile service checks again that it is the account's own image.
const props = defineProps<{ accountId: string; title?: string }>();
const emit = defineEmits<{ close: []; pick: [mediaId: string, url: string | null] }>();
const { t } = useI18n();

const ids = ref<string[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(false);
const failed = ref(false);
const urls = useMediaList(() => ids.value);

async function load(reset = false) {
  if (loading.value) return;
  loading.value = true;
  failed.value = false;
  try {
    const page = await postService.timelinePage(props.accountId, reset ? undefined : (cursor.value ?? undefined), { media: "photo" });
    const found = page.data.flatMap((p) => p.media_ids ?? []);
    ids.value = reset ? found : [...ids.value, ...found.filter((id) => !ids.value.includes(id))];
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more && !!page.page.next_cursor;
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}
onMounted(() => void load(true));

const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
useEscapeKey(ref(true), () => emit("close"));
const heading = computed(() => props.title || t("profileTools.picker.title"));
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[75] flex items-end justify-center bg-gray-950/60 backdrop-blur-sm sm:items-center sm:p-4">
      <div class="fixed inset-0" @click="emit('close')" />
      <div
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="photo-picker-title"
        tabindex="-1"
        class="card relative z-10 flex max-h-[85vh] w-full flex-col rounded-b-none p-4 shadow-pop sm:max-w-2xl sm:rounded-2xl sm:p-5"
        data-testid="photo-picker"
      >
        <div class="mb-1 flex items-center justify-between gap-2">
          <h2 id="photo-picker-title" class="text-lg font-bold">{{ heading }}</h2>
          <button type="button" class="icon-btn h-9 w-9" :aria-label="t('profileTools.picker.close')" @click="emit('close')">
            <X class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <p class="mb-3 text-sm text-gray-600 dark:text-gray-400">{{ t("profileTools.picker.hint") }}</p>
        <div class="min-h-0 flex-1 overflow-y-auto">
          <LoadingSkeleton v-if="loading && !ids.length" :rows="2" />
          <ErrorState v-else-if="failed && !ids.length" @retry="load(true)" />
          <EmptyState v-else-if="!ids.length">{{ t("profileTools.picker.empty") }}</EmptyState>
          <ul v-else class="grid grid-cols-3 gap-1.5 sm:grid-cols-4">
            <li v-for="(id, i) in ids" :key="id">
              <button
                type="button"
                class="block aspect-square w-full overflow-hidden rounded-lg bg-gray-100 transition hover:opacity-90 focus:outline-none focus-visible:ring-4 focus-visible:ring-brand-400 disabled:opacity-50 dark:bg-gray-800"
                :aria-label="t('profileTools.picker.use', { n: i + 1 })"
                :disabled="!urls[i]"
                data-testid="photo-picker-item"
                @click="emit('pick', id, urls[i] ?? null)"
              >
                <img v-if="urls[i]" :src="urls[i] ?? undefined" alt="" class="h-full w-full object-cover" loading="lazy" />
              </button>
            </li>
          </ul>
          <div v-if="hasMore && ids.length" class="mt-3 flex justify-center">
            <button type="button" class="btn-ghost" :disabled="loading" @click="load()">
              {{ loading ? t("states.loading") : t("feed.loadMore") }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
