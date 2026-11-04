<script setup lang="ts">
import { CornerDownLeft, ThumbsUp } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import StudioPostThumb from "@/components/studio/StudioPostThumb.vue";
import { useStudioComposer } from "@/components/studio/studioComposer";
import { relativeTime } from "@/lib/format";
import { type StudioComment, studioService } from "@/services/studio";
import { useDirectoryStore } from "@/stores/directory";

defineOptions({ name: "StudioEngagementView" });

/**
 * Studio Engagement → Comments: other people's comments on my published posts,
 * newest first (the post service leaves out deleted and removed comments and
 * anyone in a block with me). Each row opens the post, where the reply happens.
 */
const { t } = useI18n();
const directory = useDirectoryStore();

const rows = ref<StudioComment[]>([]);
const cursor = ref<string | null>(null);
const more = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const failed = ref(false);

async function load(reset = true) {
  if (reset) {
    loading.value = !rows.value.length;
    failed.value = false;
  } else {
    if (loadingMore.value) return;
    loadingMore.value = true;
  }
  try {
    const page = await studioService.comments(reset ? null : cursor.value);
    rows.value = reset ? page.data : [...rows.value, ...page.data];
    cursor.value = page.page?.next_cursor ?? null;
    more.value = !!page.page?.has_more;
  } catch {
    if (reset) failed.value = true;
  } finally {
    loading.value = false;
    loadingMore.value = false;
  }
}
onMounted(() => load());
watch(useStudioComposer().version, () => load());

// The post page scrolls to the comment (and opens its thread for a reply).
const postLink = (c: StudioComment) => ({
  path: `/posts/${c.post_id}`,
  query: c.parent_id ? { comment: c.id, thread: c.parent_id } : { comment: c.id },
});
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-4" data-testid="studio-engagement">
    <header class="card p-5">
      <h1 class="text-2xl font-extrabold tracking-tight text-gray-900 dark:text-white">{{ t("studio.engagement.title") }}</h1>
      <p class="mt-1 text-sm text-gray-600 dark:text-gray-300">{{ t("studio.engagement.subtitle") }}</p>
    </header>

    <LoadingSkeleton v-if="loading" />
    <ErrorState v-else-if="failed" @retry="load()" />
    <EmptyState v-else-if="!rows.length" class="card">{{ t("studio.engagement.empty") }}</EmptyState>
    <section v-else class="card divide-y divide-gray-100 dark:divide-gray-800" :aria-label="t('studio.engagement.title')">
      <ul data-testid="studio-comments">
        <li v-for="c in rows" :key="c.id" class="p-3 sm:p-4" :data-comment="c.id">
          <div class="flex items-start gap-3">
            <RouterLink :to="`/u/id/${c.author_id}`" class="shrink-0 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400">
              <UserAvatar :name="directory.label(c.author_id)" :media-id="directory.avatarOf(c.author_id)" :size="40" />
            </RouterLink>
            <div class="min-w-0 flex-1">
              <div class="rounded-2xl bg-gray-100 px-3 py-2 dark:bg-gray-800">
                <RouterLink :to="`/u/id/${c.author_id}`" dir="auto" class="text-sm font-semibold text-gray-900 hover:underline dark:text-gray-100">
                  {{ directory.label(c.author_id) }}
                </RouterLink>
                <p class="whitespace-pre-wrap break-words text-sm text-gray-800 dark:text-gray-100" dir="auto">{{ c.body }}</p>
              </div>
              <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 px-2 text-xs text-gray-600 dark:text-gray-300">
                <span>{{ relativeTime(c.created_at) }}</span>
                <span v-if="c.parent_id">{{ t("studio.engagement.isReply") }}</span>
                <span v-if="c.reaction_count" class="inline-flex items-center gap-1">
                  <ThumbsUp class="h-3 w-3" aria-hidden="true" />{{ c.reaction_count }}
                </span>
                <RouterLink :to="postLink(c)" class="inline-flex items-center gap-1 font-semibold text-brand-700 hover:underline dark:text-brand-300" data-testid="studio-comment-open">
                  <CornerDownLeft class="h-3 w-3 rtl:-scale-x-100" aria-hidden="true" />{{ t("studio.engagement.reply") }}
                </RouterLink>
              </div>
              <RouterLink :to="postLink(c)" class="mt-2 flex items-center gap-2 rounded-xl border border-gray-200 p-2 text-xs text-gray-600 hover:bg-gray-50 dark:border-gray-800 dark:text-gray-300 dark:hover:bg-gray-800/60">
                <StudioPostThumb :type="c.post_type" :size="28" />
                <span class="min-w-0 flex-1 truncate" dir="auto">{{ t("studio.engagement.on", { post: c.post_excerpt || t("studio.library.noText") }) }}</span>
              </RouterLink>
            </div>
          </div>
        </li>
      </ul>
      <div v-if="more" class="p-3 text-center">
        <button type="button" class="btn-ghost" :disabled="loadingMore" data-testid="studio-comments-more" @click="load(false)">
          {{ t("studio.engagement.loadMore") }}
        </button>
      </div>
    </section>
  </div>
</template>
