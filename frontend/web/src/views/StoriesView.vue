<script setup lang="ts">
import { Archive, Plus, Star } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import CloseFriendsDialog from "@/components/stories/CloseFriendsDialog.vue";
import StoryCreateDialog from "@/components/stories/StoryCreateDialog.vue";
import StoryTrayCard from "@/components/stories/StoryTrayCard.vue";
import StoryViewer from "@/components/stories/StoryViewer.vue";
import { relativeTime } from "@/lib/format";
import { storiesService, type Story, type StoryGroup } from "@/services/stories";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";

// /stories: your story (create, archive, close friends) beside every story in
// your tray. /stories/:id opens one story (a notification link); a story you
// may not see, or one that expired, is "not available" (the server says 404).
const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const directory = useDirectoryStore();

const groups = ref<StoryGroup[]>([]);
const loading = ref(true);
const failed = ref(false);
const creating = ref(false);
const editingCloseFriends = ref(false);

// The viewer: either the tray (from a card) or one author's stories (a deep link).
const viewerGroups = ref<StoryGroup[] | null>(null);
const viewerStart = ref(0);
const viewerStory = ref<number | null>(null);
const unavailable = ref(false);

const meId = computed(() => auth.account?.id ?? "");
const myName = computed(() => auth.profile?.display_name || auth.account?.email?.split("@")[0] || "?");
const mine = computed(() => groups.value.find((g) => g.author_id === meId.value));
const others = computed(() => groups.value.filter((g) => g.author_id !== meId.value));

async function load() {
  loading.value = true;
  failed.value = false;
  try {
    groups.value = await storiesService.tray();
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

function openGroup(authorId: string) {
  const i = groups.value.findIndex((g) => g.author_id === authorId);
  if (i < 0) return;
  viewerGroups.value = groups.value;
  viewerStart.value = i;
  viewerStory.value = null;
}

async function openDeepLink(id: string) {
  unavailable.value = false;
  try {
    const story = await storiesService.get(id);
    // My own story stays open after it expires (the archive); others' are active only.
    const list = story.is_mine && !story.is_active ? [story] : await storiesService.ofAuthor(story.author_id);
    const stories = list.some((s) => s.id === story.id) ? list : [story];
    viewerGroups.value = [
      { author_id: story.author_id, has_unseen: stories.some((s) => !s.seen), latest_at: story.created_at, stories },
    ];
    viewerStart.value = 0;
    viewerStory.value = Math.max(0, stories.findIndex((s) => s.id === story.id));
  } catch {
    unavailable.value = true;
  }
}

function closeViewer() {
  viewerGroups.value = null;
  if (route.params.id) void router.replace({ name: "stories" });
  void load();
}

function onStory(updated: Story) {
  const g = groups.value.find((x) => x.author_id === updated.author_id);
  if (!g) return;
  g.stories = g.stories.map((s) => (s.id === updated.id ? updated : s));
  g.has_unseen = updated.author_id !== meId.value && g.stories.some((s) => !s.seen);
}

watch(
  () => route.params.id,
  (id) => {
    if (typeof id === "string" && id) void openDeepLink(id);
    else unavailable.value = false;
  },
  { immediate: true },
);
onMounted(() => {
  void load();
  // The "Create" menu's Story entry lands here with ?create=1.
  if (route.query.create === "1") {
    creating.value = true;
    void router.replace({ query: { ...route.query, create: undefined } });
  }
});

const navRow =
  "flex w-full items-center gap-3 rounded-xl px-2 py-2 text-start text-[15px] font-semibold transition hover:bg-gray-100 dark:hover:bg-gray-800";
</script>

<template>
  <AppShell :left="false" :right="false">
    <div class="mx-auto flex w-full max-w-[1100px] flex-col gap-4 lg:flex-row lg:items-start">
      <aside class="card w-full shrink-0 p-3 lg:sticky lg:top-20 lg:w-80" :aria-label="t('stories.title')" data-testid="stories-nav">
        <h1 class="px-2 text-2xl font-bold">{{ t("stories.title") }}</h1>
        <p class="px-2 pb-3 text-sm text-gray-500 dark:text-gray-400">{{ t("stories.hub.subtitle") }}</p>

        <h2 class="px-2 pb-1 text-[15px] font-semibold">{{ t("stories.hub.yourStory") }}</h2>
        <ul class="space-y-0.5">
          <li>
            <button type="button" :class="navRow" data-testid="stories-create" @click="creating = true">
              <span class="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700 dark:bg-brand-950/60 dark:text-brand-300">
                <Plus class="h-6 w-6" aria-hidden="true" />
              </span>
              <span class="min-w-0">
                <span class="block">{{ t("stories.create.title") }}</span>
                <span class="block text-xs font-normal text-gray-500 dark:text-gray-400">{{ t("stories.hub.yourStoryHint") }}</span>
              </span>
            </button>
          </li>
          <li v-if="mine">
            <button type="button" :class="navRow" data-testid="stories-mine" @click="openGroup(meId)">
              <span class="rounded-full bg-gradient-to-br from-brand-600 to-accent-500 p-[3px]">
                <UserAvatar :name="myName" :media-id="auth.profile?.avatar_media_id" :size="42" class="ring-2 ring-white dark:ring-gray-900" />
              </span>
              <span class="min-w-0">
                <span class="block">{{ t("stories.rail.yourStory") }}</span>
                <span class="block text-xs font-normal text-gray-500 dark:text-gray-400">{{ relativeTime(mine.latest_at) }}</span>
              </span>
            </button>
          </li>
          <li>
            <RouterLink to="/stories/archive" :class="navRow" data-testid="stories-archive-link">
              <span class="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200">
                <Archive class="h-5 w-5" aria-hidden="true" />
              </span>
              <span class="min-w-0">
                <span class="block">{{ t("stories.hub.archive") }}</span>
                <span class="block text-xs font-normal text-gray-500 dark:text-gray-400">{{ t("stories.hub.archiveHint") }}</span>
              </span>
            </RouterLink>
          </li>
          <li>
            <button type="button" :class="navRow" data-testid="stories-close-friends" @click="editingCloseFriends = true">
              <span class="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
                <Star class="h-5 w-5" aria-hidden="true" />
              </span>
              <span class="min-w-0">
                <span class="block">{{ t("stories.hub.closeFriends") }}</span>
                <span class="block text-xs font-normal text-gray-500 dark:text-gray-400">{{ t("stories.hub.closeFriendsHint") }}</span>
              </span>
            </button>
          </li>
        </ul>

        <div v-if="others.length" class="mt-3 border-t border-gray-100 pt-3 dark:border-gray-800">
          <h2 class="px-2 pb-1 text-[15px] font-semibold">{{ t("stories.hub.allStories") }}</h2>
          <ul class="space-y-0.5">
            <li v-for="g in others" :key="g.author_id">
              <button type="button" :class="navRow" @click="openGroup(g.author_id)">
                <span class="rounded-full p-[3px]" :class="g.has_unseen ? 'bg-gradient-to-br from-brand-600 to-accent-500' : 'bg-gray-300 dark:bg-gray-700'">
                  <UserAvatar :name="directory.label(g.author_id)" :media-id="directory.avatarOf(g.author_id)" :size="42" class="ring-2 ring-white dark:ring-gray-900" />
                </span>
                <span class="min-w-0">
                  <span dir="auto" class="block truncate">{{ directory.label(g.author_id) }}</span>
                  <span class="block text-xs font-normal" :class="g.has_unseen ? 'text-brand-700 dark:text-brand-300' : 'text-gray-500 dark:text-gray-400'">
                    {{ relativeTime(g.latest_at) }}
                  </span>
                </span>
              </button>
            </li>
          </ul>
        </div>
      </aside>

      <section class="min-w-0 flex-1" :aria-label="t('stories.hub.allStories')">
        <div v-if="unavailable" class="card p-6 text-center" data-testid="story-unavailable">
          <p class="text-sm text-gray-700 dark:text-gray-200">{{ t("stories.viewer.unavailable") }}</p>
          <RouterLink to="/home" class="btn-soft mt-3">{{ t("stories.viewer.backHome") }}</RouterLink>
        </div>
        <LoadingSkeleton v-else-if="loading" :rows="2" />
        <ErrorState v-else-if="failed" @retry="load" />
        <EmptyState v-else-if="!groups.length">{{ t("stories.hub.empty") }}</EmptyState>
        <div v-else class="card p-4">
          <h2 class="mb-3 text-lg font-bold">{{ t("stories.hub.allStories") }}</h2>
          <div class="grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] gap-2 [&>button]:w-full" data-testid="stories-grid">
            <StoryTrayCard
              v-for="g in groups"
              :key="g.author_id"
              :group="g"
              :mine="g.author_id === meId"
              @open="openGroup(g.author_id)"
            />
          </div>
        </div>
      </section>
    </div>

    <StoryViewer
      v-if="viewerGroups"
      :groups="viewerGroups"
      :start-group="viewerStart"
      :start-story="viewerStory"
      can-create
      @close="closeViewer"
      @story="onStory"
      @create="closeViewer(); creating = true"
    />
    <StoryCreateDialog v-if="creating" @close="creating = false" @created="load" />
    <CloseFriendsDialog v-if="editingCloseFriends" @close="editingCloseFriends = false" />
  </AppShell>
</template>
