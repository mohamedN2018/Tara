<script setup lang="ts">
import { ArrowLeft, ArrowRight } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import StoryArchiveTile from "@/components/stories/StoryArchiveTile.vue";
import StoryViewer from "@/components/stories/StoryViewer.vue";
import { storiesService, type Story, type StoryGroup } from "@/services/stories";
import { useToastStore } from "@/stores/toasts";

// My story archive: every story I shared, active or expired, newest first.
// Only I can open it (the server scopes it to the caller). Opening one plays
// the archive in the order shared, with the viewer list on each story.
const { t, locale } = useI18n();
const toasts = useToastStore();

const stories = ref<Story[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const failed = ref(false);
const viewing = ref<{ groups: StoryGroup[]; index: number } | null>(null);

const BackIcon = computed(() => (locale.value === "ar" ? ArrowRight : ArrowLeft));

async function load(more = false) {
  if (more) loadingMore.value = true;
  else {
    loading.value = true;
    failed.value = false;
  }
  try {
    const page = await storiesService.archive(more ? cursor.value : null);
    stories.value = more ? [...stories.value, ...page.data] : page.data;
    cursor.value = page.page?.next_cursor ?? null;
    hasMore.value = !!page.page?.has_more;
  } catch (e) {
    if (more) toasts.error(e);
    else failed.value = true;
  } finally {
    loading.value = false;
    loadingMore.value = false;
  }
}
onMounted(() => load());

function open(story: Story) {
  // Played oldest first, like the rail.
  const ordered = [...stories.value].reverse();
  viewing.value = {
    groups: [{ author_id: story.author_id, has_unseen: false, latest_at: story.created_at, stories: ordered }],
    index: ordered.findIndex((s) => s.id === story.id),
  };
}
function onStory(updated: Story) {
  stories.value = stories.value.map((s) => (s.id === updated.id ? updated : s));
}
function onDeleted(id: string) {
  stories.value = stories.value.filter((s) => s.id !== id);
}
</script>

<template>
  <AppShell :right="false">
    <div class="mx-auto w-full max-w-[900px] space-y-4">
      <header class="card p-4">
        <RouterLink to="/stories" class="mb-2 inline-flex items-center gap-1 text-sm font-semibold text-brand-700 hover:underline dark:text-brand-300">
          <component :is="BackIcon" class="h-4 w-4" aria-hidden="true" />{{ t("stories.title") }}
        </RouterLink>
        <h1 class="text-2xl font-bold">{{ t("stories.archive.title") }}</h1>
        <p class="text-sm text-gray-500 dark:text-gray-400">{{ t("stories.archive.subtitle") }}</p>
      </header>

      <LoadingSkeleton v-if="loading" :rows="2" />
      <ErrorState v-else-if="failed" @retry="load()" />
      <EmptyState v-else-if="!stories.length">{{ t("stories.archive.empty") }}</EmptyState>
      <section v-else class="card p-4">
        <ul class="grid grid-cols-[repeat(auto-fill,minmax(130px,1fr))] gap-3" data-testid="story-archive-grid">
          <li v-for="s in stories" :key="s.id">
            <StoryArchiveTile :story="s" @open="open(s)" />
          </li>
        </ul>
        <button v-if="hasMore" type="button" class="btn-ghost mt-3 w-full" :disabled="loadingMore" @click="load(true)">
          {{ t("stories.archive.loadMore") }}
        </button>
      </section>
    </div>

    <StoryViewer
      v-if="viewing"
      :groups="viewing.groups"
      :start-story="viewing.index"
      @close="viewing = null"
      @story="onStory"
      @deleted="onDeleted"
    />
  </AppShell>
</template>
