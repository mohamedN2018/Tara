<script setup lang="ts">
// The reels viewer (roadmap 5.8): a full-height vertical pager that snaps one
// reel per screen. Only the active reel and its two neighbours mount a player
// (at most 3 <video> elements, pager.ts); the active one autoplays muted and
// loops. One tap pauses or resumes, a double tap likes. The action rail sits on
// the end side (right in English, left in Arabic); swiping stays vertical, so
// nothing about it mirrors. Arrow keys / j / k move between reels, Space
// pauses, m mutes. All writes are the parent's (it owns the list).
import { ChevronDown, ChevronUp, Heart, MessageCircle, MoreHorizontal, Pause, Share2, Volume2, VolumeX } from "lucide-vue-next";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { mediaService } from "@/services/media";
import type { Reel } from "@/services/reels";
import { useDirectoryStore } from "@/stores/directory";
import { usePageDirectoryStore } from "@/stores/pageDirectory";

import { compactCount, createTapDetector, indexFromScroll, isMounted, reelsMuted } from "./pager";
import ReelPlayer from "./ReelPlayer.vue";

const props = withDefaults(defineProps<{ reels: Reel[]; startIndex?: number; hasMore?: boolean }>(), {
  startIndex: 0,
  hasMore: false,
});
const emit = defineEmits<{
  active: [index: number];
  more: [];
  like: [reel: Reel];
  unlike: [reel: Reel];
  comments: [reel: Reel];
  share: [reel: Reel];
  menu: [reel: Reel];
  watched: [reel: Reel];
}>();

const { t, locale } = useI18n();
const directory = useDirectoryStore();
const pageDirectory = usePageDirectoryStore();

const scroller = ref<HTMLElement | null>(null);
const active = ref(Math.max(0, props.startIndex));
const players = ref<Record<string, InstanceType<typeof ReelPlayer> | null>>({});
const pausedIds = ref<Record<string, boolean>>({});
const heartAt = ref<string | null>(null);
const covers = ref<Record<string, string | null>>({});
let heartTimer: ReturnType<typeof setTimeout> | null = null;
let frame = 0;

const current = computed(() => props.reels[active.value] ?? null);

function setActive(index: number) {
  if (index === active.value || index < 0 || index >= props.reels.length) return;
  active.value = index;
}

watch(
  active,
  (index) => {
    emit("active", index);
    if (props.hasMore && index >= props.reels.length - 2) emit("more");
    loadCovers();
  },
  { immediate: false },
);
watch(
  () => props.reels.length,
  (length) => {
    if (active.value >= length) active.value = Math.max(0, length - 1);
    if (props.hasMore && active.value >= length - 2) emit("more");
    loadCovers();
  },
);

/** Covers of the mounted reels, resolved once (they follow the reel's audience). */
function loadCovers() {
  props.reels.forEach((reel, i) => {
    const id = reel.reel.cover_media_id;
    if (!id || reel.id in covers.value || !isMounted(i, active.value, props.reels.length)) return;
    covers.value = { ...covers.value, [reel.id]: null };
    void mediaService.resolveUrl(id).then((url) => {
      covers.value = { ...covers.value, [reel.id]: url };
    });
  });
}

function onScroll() {
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    const el = scroller.value;
    if (el) setActive(indexFromScroll(el.scrollTop, el.clientHeight, props.reels.length));
  });
}

function goTo(index: number, smooth = true) {
  const el = scroller.value;
  if (index < 0 || index >= props.reels.length) return;
  setActive(index);
  if (el) el.scrollTo({ top: index * el.clientHeight, behavior: smooth ? "smooth" : "auto" });
}

function like(reel: Reel) {
  if (reel.my_reaction) emit("unlike", reel);
  else emit("like", reel);
}

function burst(reel: Reel) {
  heartAt.value = reel.id;
  if (heartTimer) clearTimeout(heartTimer);
  heartTimer = setTimeout(() => (heartAt.value = null), 800);
}

// One detector per pager: taps on another reel are never paired.
let tapTarget: Reel | null = null;
const tap = createTapDetector(
  () => {
    if (tapTarget) players.value[tapTarget.id]?.toggle();
  },
  () => {
    const reel = tapTarget;
    if (!reel) return;
    burst(reel);
    if (!reel.my_reaction) emit("like", reel); // a double tap only ever likes
  },
);
function onTap(reel: Reel) {
  if (tapTarget && tapTarget.id !== reel.id) tapTarget = null;
  tapTarget = reel;
  tap();
}

function onKey(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
  if (e.key === "ArrowDown" || e.key === "PageDown" || e.key === "j") {
    e.preventDefault();
    goTo(active.value + 1);
  } else if (e.key === "ArrowUp" || e.key === "PageUp" || e.key === "k") {
    e.preventDefault();
    goTo(active.value - 1);
  } else if (e.key === " " && current.value && e.target === scroller.value) {
    e.preventDefault();
    players.value[current.value.id]?.toggle();
  } else if (e.key === "m") {
    reelsMuted.value = !reelsMuted.value;
  }
}

function setPlayer(id: string, el: unknown) {
  players.value[id] = (el as InstanceType<typeof ReelPlayer> | null) ?? null;
}

function onPlaying(reel: Reel) {
  pausedIds.value = { ...pausedIds.value, [reel.id]: false };
  if (current.value?.id === reel.id) emit("watched", reel);
}
function onPaused(reel: Reel, index: number) {
  // A reel scrolled away is paused too; only the active one shows the pause badge.
  pausedIds.value = { ...pausedIds.value, [reel.id]: index === active.value };
}

const byPage = (reel: Reel) => reel.author_type === "page";
const name = (reel: Reel) => (byPage(reel) ? pageDirectory.label(reel.author_id) : directory.label(reel.author_id));
const avatar = (reel: Reel) => (byPage(reel) ? pageDirectory.avatarOf(reel.author_id) : directory.avatarOf(reel.author_id));
const authorLink = (reel: Reel) => ({ name: byPage(reel) ? "page-by-id" : "profile-by-id", params: { id: reel.author_id } });
const count = (n: number) => compactCount(n, locale.value);

onMounted(async () => {
  await nextTick();
  if (active.value) goTo(active.value, false);
  emit("active", active.value);
  loadCovers();
});
watch(
  () => props.startIndex,
  async (index) => {
    await nextTick();
    goTo(index, false);
  },
);
onBeforeUnmount(() => {
  if (heartTimer) clearTimeout(heartTimer);
  if (frame) cancelAnimationFrame(frame);
});

defineExpose({ goTo, active });
</script>

<template>
  <section class="relative h-full w-full" :aria-label="t('reels.viewer')" data-testid="reel-pager" :data-active="active">
    <div
      ref="scroller"
      class="h-full snap-y snap-mandatory overflow-y-auto overscroll-contain [scrollbar-width:none] focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 [&::-webkit-scrollbar]:hidden"
      tabindex="0"
      :aria-label="t('reels.keyboardHint')"
      data-testid="reel-scroller"
      @scroll.passive="onScroll"
      @keydown="onKey"
    >
      <article
        v-for="(reel, i) in reels"
        :key="reel.id"
        class="relative flex h-full snap-start snap-always items-center justify-center py-0 sm:py-2"
        :aria-label="t('reels.byAuthor', { name: name(reel) })"
        :aria-current="i === active ? 'true' : undefined"
        data-testid="reel-slide"
        :data-reel-id="reel.id"
      >
        <div class="relative flex h-full max-w-full items-end gap-3">
          <div class="relative aspect-[9/16] h-full max-w-[100vw] overflow-hidden bg-black sm:rounded-2xl">
            <ReelPlayer
              v-if="isMounted(i, active, reels.length)"
              :ref="(el) => setPlayer(reel.id, el)"
              :media-id="reel.reel.media_id"
              :active="i === active"
              :cover="covers[reel.id] ?? null"
              :label="t('reels.byAuthor', { name: name(reel) })"
              @playing="onPlaying(reel)"
              @paused="onPaused(reel, i)"
            />
            <div v-else class="h-full w-full bg-gradient-to-br from-gray-950 via-brand-950 to-gray-900" aria-hidden="true" />

            <!-- Tap: pause / play. Double tap: like. -->
            <button
              type="button"
              class="absolute inset-0 z-10 focus:outline-none"
              :aria-label="pausedIds[reel.id] ? t('reels.play') : t('reels.pause')"
              data-testid="reel-tap"
              @click="onTap(reel)"
            />
            <Pause
              v-if="pausedIds[reel.id] && i === active"
              class="pointer-events-none absolute inset-0 z-10 m-auto h-16 w-16 rounded-full bg-black/45 p-4 text-white"
              aria-hidden="true"
              data-testid="reel-paused"
            />
            <Heart
              v-if="heartAt === reel.id"
              class="pointer-events-none absolute inset-0 z-20 m-auto h-24 w-24 animate-pop-in fill-accent-500 text-accent-500 drop-shadow-lg"
              aria-hidden="true"
              data-testid="reel-heart"
            />

            <!-- Mute -->
            <button
              type="button"
              class="absolute end-3 top-3 z-20 rounded-full bg-black/45 p-2 text-white hover:bg-black/65 focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
              :aria-label="reelsMuted ? t('reels.unmute') : t('reels.mute')"
              :aria-pressed="!reelsMuted"
              data-testid="reel-mute"
              @click="reelsMuted = !reelsMuted"
            >
              <VolumeX v-if="reelsMuted" class="h-5 w-5" aria-hidden="true" />
              <Volume2 v-else class="h-5 w-5" aria-hidden="true" />
            </button>

            <!-- Author, caption, views -->
            <div class="pointer-events-none absolute inset-x-0 bottom-0 z-20 bg-gradient-to-t from-black/80 via-black/40 to-transparent px-3 pb-4 pt-16 text-white sm:pe-3">
              <RouterLink
                :to="authorLink(reel)"
                class="pointer-events-auto inline-flex max-w-[75%] items-center gap-2 rounded-full pe-2 font-semibold hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
                data-testid="reel-author"
              >
                <UserAvatar :name="name(reel)" :media-id="avatar(reel)" :size="32" ring />
                <span class="truncate" dir="auto">{{ name(reel) }}</span>
              </RouterLink>
              <p v-if="reel.body" class="mt-2 line-clamp-3 whitespace-pre-line text-sm" dir="auto" data-testid="reel-caption">{{ reel.body }}</p>
              <p class="mt-1 text-xs text-white/80" data-testid="reel-views">{{ t("reels.views", { n: count(reel.reel.view_count) }, reel.reel.view_count) }}</p>
            </div>

          </div>

          <!-- Actions on the end side: over the frame on phones, beside it from sm up -->
          <div
            class="absolute bottom-28 end-2 z-20 flex flex-col items-center gap-4 text-white drop-shadow sm:static sm:pb-6 sm:text-gray-800 sm:drop-shadow-none dark:sm:text-gray-100"
            data-testid="reel-actions"
          >
            <button
              type="button"
              class="flex flex-col items-center gap-1 text-xs font-semibold focus:outline-none"
              :aria-label="reel.my_reaction ? t('reels.unlike') : t('reels.like')"
              :aria-pressed="!!reel.my_reaction"
              data-testid="reel-like"
              @click="like(reel)"
            >
              <span class="flex h-12 w-12 items-center justify-center rounded-full bg-black/35 transition hover:bg-black/50 sm:bg-gray-200 sm:hover:bg-gray-300 dark:sm:bg-gray-800 dark:sm:hover:bg-gray-700">
                <Heart class="h-6 w-6" :class="reel.my_reaction ? 'fill-accent-500 text-accent-500' : ''" aria-hidden="true" />
              </span>
              <span data-testid="reel-like-count">{{ count(reel.reaction_count) }}</span>
            </button>
            <button
              type="button"
              class="flex flex-col items-center gap-1 text-xs font-semibold focus:outline-none"
              :aria-label="t('reels.comments', { n: reel.comment_count }, reel.comment_count)"
              data-testid="reel-comment"
              @click="emit('comments', reel)"
            >
              <span class="flex h-12 w-12 items-center justify-center rounded-full bg-black/35 transition hover:bg-black/50 sm:bg-gray-200 sm:hover:bg-gray-300 dark:sm:bg-gray-800 dark:sm:hover:bg-gray-700">
                <MessageCircle class="h-6 w-6 rtl:-scale-x-100" aria-hidden="true" />
              </span>
              <span>{{ count(reel.comment_count) }}</span>
            </button>
            <button
              type="button"
              class="flex flex-col items-center gap-1 text-xs font-semibold focus:outline-none"
              :aria-label="t('reels.share')"
              data-testid="reel-share"
              @click="emit('share', reel)"
            >
              <span class="flex h-12 w-12 items-center justify-center rounded-full bg-black/35 transition hover:bg-black/50 sm:bg-gray-200 sm:hover:bg-gray-300 dark:sm:bg-gray-800 dark:sm:hover:bg-gray-700">
                <Share2 class="h-6 w-6" aria-hidden="true" />
              </span>
              <span>{{ count(reel.share_count) }}</span>
            </button>
            <button
              type="button"
              class="flex h-12 w-12 items-center justify-center rounded-full bg-black/35 transition hover:bg-black/50 focus:outline-none sm:bg-gray-200 sm:hover:bg-gray-300 dark:sm:bg-gray-800 dark:sm:hover:bg-gray-700"
              :aria-label="t('reels.more')"
              data-testid="reel-more"
              @click="emit('menu', reel)"
            >
              <MoreHorizontal class="h-6 w-6" aria-hidden="true" />
            </button>
          </div>
        </div>
      </article>
    </div>

    <!-- Previous / next (desktop). Vertical, so the same in both directions. -->
    <div class="absolute end-4 top-1/2 z-30 hidden -translate-y-1/2 flex-col gap-3 lg:flex">
      <button
        type="button"
        class="flex h-11 w-11 items-center justify-center rounded-full bg-white text-gray-800 shadow-lg hover:bg-gray-100 disabled:opacity-40 dark:bg-gray-800 dark:text-gray-100"
        :aria-label="t('reels.prev')"
        :disabled="active === 0"
        data-testid="reel-prev"
        @click="goTo(active - 1)"
      >
        <ChevronUp class="h-6 w-6" aria-hidden="true" />
      </button>
      <button
        type="button"
        class="flex h-11 w-11 items-center justify-center rounded-full bg-white text-gray-800 shadow-lg hover:bg-gray-100 disabled:opacity-40 dark:bg-gray-800 dark:text-gray-100"
        :aria-label="t('reels.next')"
        :disabled="active >= reels.length - 1"
        data-testid="reel-next"
        @click="goTo(active + 1)"
      >
        <ChevronDown class="h-6 w-6" aria-hidden="true" />
      </button>
    </div>
  </section>
</template>
