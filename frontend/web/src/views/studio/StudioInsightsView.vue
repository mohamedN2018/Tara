<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import StudioPostThumb from "@/components/studio/StudioPostThumb.vue";
import { useStudioComposer } from "@/components/studio/studioComposer";
import type { ComposerPost } from "@/services/composer";
import { type StudioInsights, studioService } from "@/services/studio";

defineOptions({ name: "StudioInsightsView" });

/**
 * Studio Insights → Content performance: my published posts per post type with
 * the reactions, comments and shares they received (and the average per post),
 * then my ten posts with the most interactions. Only counters the post service
 * really keeps; there is no reach or view count, and the page says so.
 */
const { t, locale } = useI18n();

const data = ref<StudioInsights | null>(null);
const loading = ref(true);
const failed = ref(false);

async function load() {
  loading.value = !data.value;
  failed.value = false;
  try {
    data.value = await studioService.insights();
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(useStudioComposer().version, load);

const fmt = (n: number) => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 1 }).format(n);
const typeLabel = (type: string) => t(`studio.library.types.${type}`);
const perPost = (r: { posts: number; reactions: number; comments: number; shares: number }) =>
  r.posts ? (r.reactions + r.comments + r.shares) / r.posts : 0;
const interactions = (p: ComposerPost) => p.reaction_count + p.comment_count + p.share_count;
const excerpt = (p: ComposerPost) => (p.body || "").trim() || t("studio.library.noText");
const rows = computed(() => data.value?.by_type ?? []);
const cell = "px-3 py-2.5 text-end tabular-nums";
</script>

<template>
  <div class="mx-auto max-w-5xl space-y-4" data-testid="studio-insights">
    <header class="card p-5">
      <h1 class="text-2xl font-extrabold tracking-tight text-gray-900 dark:text-white">{{ t("studio.insights.title") }}</h1>
      <p class="mt-1 text-sm text-gray-600 dark:text-gray-300">{{ t("studio.insights.subtitle") }}</p>
    </header>

    <LoadingSkeleton v-if="loading" />
    <ErrorState v-else-if="failed" @retry="load" />
    <template v-else-if="data">
      <section class="card overflow-hidden" aria-labelledby="insights-by-type">
        <h2 id="insights-by-type" class="section-title px-4 pt-4">{{ t("studio.insights.byType") }}</h2>
        <p v-if="!rows.length" class="p-4 text-sm text-gray-600 dark:text-gray-300">{{ t("studio.insights.empty") }}</p>
        <div v-else class="mt-2 overflow-x-auto">
          <table class="w-full min-w-[34rem] text-sm" data-testid="insights-by-type">
            <thead class="bg-gray-50 text-xs font-semibold text-gray-600 dark:bg-gray-800/60 dark:text-gray-300">
              <tr>
                <th scope="col" class="px-3 py-2 text-start">{{ t("studio.insights.cols.type") }}</th>
                <th scope="col" class="px-3 py-2 text-end">{{ t("studio.insights.cols.posts") }}</th>
                <th scope="col" class="px-3 py-2 text-end">{{ t("studio.insights.cols.reactions") }}</th>
                <th scope="col" class="px-3 py-2 text-end">{{ t("studio.insights.cols.comments") }}</th>
                <th scope="col" class="px-3 py-2 text-end">{{ t("studio.insights.cols.shares") }}</th>
                <th scope="col" class="px-3 py-2 text-end">{{ t("studio.insights.cols.perPost") }}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-100 dark:divide-gray-800">
              <tr v-for="r in rows" :key="r.type" :data-type="r.type">
                <th scope="row" class="px-3 py-2.5 text-start font-semibold text-gray-900 dark:text-gray-100">
                  <span class="inline-flex items-center gap-2">
                    <StudioPostThumb :type="r.type" :size="24" />{{ typeLabel(r.type) }}
                  </span>
                </th>
                <td :class="cell">{{ fmt(r.posts) }}</td>
                <td :class="cell">{{ fmt(r.reactions) }}</td>
                <td :class="cell">{{ fmt(r.comments) }}</td>
                <td :class="cell">{{ fmt(r.shares) }}</td>
                <td :class="[cell, 'font-semibold']">{{ fmt(perPost(r)) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card p-4" aria-labelledby="insights-top">
        <h2 id="insights-top" class="section-title">{{ t("studio.insights.top") }}</h2>
        <ol v-if="data.top_posts.length" class="mt-3 divide-y divide-gray-100 dark:divide-gray-800" data-testid="insights-top-posts">
          <li v-for="(p, i) in data.top_posts" :key="p.id">
            <RouterLink :to="`/posts/${p.id}`" class="flex items-center gap-3 rounded-xl px-1 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-800/60">
              <span class="w-6 shrink-0 text-center text-sm font-bold text-gray-500 dark:text-gray-400">{{ fmt(i + 1) }}</span>
              <StudioPostThumb :type="p.type" :media-ids="p.media_ids" :size="44" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-semibold text-gray-900 dark:text-gray-100" dir="auto">{{ excerpt(p) }}</span>
                <span class="block text-xs text-gray-600 dark:text-gray-300">
                  {{ t("studio.home.interactions", { reactions: fmt(p.reaction_count), comments: fmt(p.comment_count), shares: fmt(p.share_count) }) }}
                </span>
              </span>
              <span class="shrink-0 text-sm font-bold text-brand-700 dark:text-brand-300">
                {{ t("studio.insights.interactions", { n: fmt(interactions(p)) }, interactions(p)) }}
              </span>
            </RouterLink>
          </li>
        </ol>
        <p v-else class="mt-3 text-sm text-gray-600 dark:text-gray-300">{{ t("studio.insights.topEmpty") }}</p>
      </section>
    </template>
  </div>
</template>
