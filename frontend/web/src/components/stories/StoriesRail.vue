<script setup lang="ts">
import { ChevronLeft, ChevronRight, Plus } from "lucide-vue-next";
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { useMediaUrl } from "@/lib/useMediaUrl";
import { storiesService, type Story, type StoryGroup } from "@/services/stories";
import { useAuthStore } from "@/stores/auth";

import StoryCreateDialog from "./StoryCreateDialog.vue";
import StoryTrayCard from "./StoryTrayCard.vue";
import StoryViewer from "./StoryViewer.vue";

// The stories rail at the top of Home: a "Create story" card, then my story and
// my friends' stories (unseen first), with arrows that scroll in the reading
// direction. A rail that can't load shows only the create card.
const { t, locale } = useI18n();
const auth = useAuthStore();

const groups = ref<StoryGroup[]>([]);
const viewing = ref<number | null>(null);
const creating = ref(false);
const scroller = ref<HTMLElement | null>(null);
const canPrev = ref(false);
const canNext = ref(false);

const meId = computed(() => auth.account?.id ?? "");
const myName = computed(() => auth.profile?.display_name || auth.account?.email?.split("@")[0] || "?");
const myAvatar = useMediaUrl(() => auth.profile?.avatar_media_id ?? null);
const isRtl = computed(() => locale.value === "ar");

async function load() {
  try {
    groups.value = await storiesService.tray();
  } catch {
    groups.value = [];
  }
  await nextTick();
  measure();
}

function measure() {
  const el = scroller.value;
  if (!el) return;
  const offset = Math.abs(el.scrollLeft);
  canPrev.value = offset > 4;
  canNext.value = offset + el.clientWidth < el.scrollWidth - 4;
}

function scroll(direction: 1 | -1) {
  const el = scroller.value;
  if (!el) return;
  // scrollLeft runs negative in RTL, so "forward" is to the left there.
  const step = Math.max(el.clientWidth * 0.8, 240) * direction * (isRtl.value ? -1 : 1);
  el.scrollBy({ left: step, behavior: "smooth" });
}

function onStory(updated: Story) {
  const g = groups.value.find((x) => x.author_id === updated.author_id);
  if (!g) return;
  g.stories = g.stories.map((s) => (s.id === updated.id ? updated : s));
  g.has_unseen = updated.author_id !== meId.value && g.stories.some((s) => !s.seen);
}
function onDeleted(id: string) {
  for (const g of groups.value) g.stories = g.stories.filter((s) => s.id !== id);
  groups.value = groups.value.filter((g) => g.stories.length);
}
function onViewerClosed() {
  viewing.value = null;
  // Authors whose stories are all seen move after the unseen ones.
  groups.value = [...groups.value].sort(
    (a, b) =>
      Number(a.author_id !== meId.value) - Number(b.author_id !== meId.value) ||
      Number(!a.has_unseen) - Number(!b.has_unseen),
  );
}
function onCreated() {
  void load();
}

let resizeObserver: ResizeObserver | undefined;
onMounted(() => {
  void load();
  if (typeof ResizeObserver !== "undefined" && scroller.value) {
    resizeObserver = new ResizeObserver(measure);
    resizeObserver.observe(scroller.value);
  }
});
// Home is kept alive: coming back refreshes the rail.
onActivated(() => void load());
onBeforeUnmount(() => resizeObserver?.disconnect());

const PrevIcon = computed(() => (isRtl.value ? ChevronRight : ChevronLeft));
const NextIcon = computed(() => (isRtl.value ? ChevronLeft : ChevronRight));
</script>

<template>
  <section class="relative" :aria-label="t('stories.rail.label')" data-testid="stories-rail">
    <div ref="scroller" class="flex gap-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden overflow-x-auto scroll-smooth pb-1" @scroll.passive="measure">
      <!-- Create story -->
      <button
        type="button"
        class="group relative flex h-[208px] w-[128px] shrink-0 flex-col overflow-hidden rounded-xl border border-gray-200/80 bg-white text-start shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 dark:border-gray-800/80 dark:bg-gray-900"
        data-testid="story-create"
        @click="creating = true"
      >
        <span class="relative h-[156px] w-full overflow-hidden bg-tara-gradient">
          <img v-if="myAvatar" :src="myAvatar" alt="" class="h-full w-full object-cover transition duration-300 group-hover:scale-105" />
          <span v-else class="flex h-full w-full items-center justify-center text-3xl font-bold text-white">{{ myName.slice(0, 1) }}</span>
        </span>
        <span class="absolute inset-x-0 top-[138px] mx-auto flex h-9 w-9 items-center justify-center rounded-full border-4 border-white bg-brand-600 text-white dark:border-gray-900">
          <Plus class="h-5 w-5" aria-hidden="true" />
        </span>
        <span class="flex flex-1 items-end justify-center pb-2.5 text-[13px] font-semibold text-gray-900 dark:text-gray-100">
          {{ t("stories.rail.create") }}
        </span>
      </button>

      <StoryTrayCard
        v-for="(g, i) in groups"
        :key="g.author_id"
        :group="g"
        :mine="g.author_id === meId"
        @open="viewing = i"
      />
    </div>

    <button
      v-show="canPrev"
      type="button"
      class="absolute start-2 top-[104px] z-10 inline-flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-white text-gray-700 shadow-pop hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-100"
      :aria-label="t('stories.rail.prev')"
      @click="scroll(-1)"
    >
      <component :is="PrevIcon" class="h-5 w-5" aria-hidden="true" />
    </button>
    <button
      v-show="canNext"
      type="button"
      class="absolute end-2 top-[104px] z-10 inline-flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-white text-gray-700 shadow-pop hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-100"
      :aria-label="t('stories.rail.next')"
      data-testid="stories-rail-next"
      @click="scroll(1)"
    >
      <component :is="NextIcon" class="h-5 w-5" aria-hidden="true" />
    </button>

    <StoryViewer
      v-if="viewing !== null"
      :groups="groups"
      :start-group="viewing"
      can-create
      @close="onViewerClosed"
      @story="onStory"
      @deleted="onDeleted"
      @create="onViewerClosed(); creating = true"
    />
    <StoryCreateDialog v-if="creating" @close="creating = false" @created="onCreated" />
  </section>
</template>
