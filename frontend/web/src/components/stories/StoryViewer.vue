<script setup lang="ts">
import {
  ChevronLeft,
  ChevronRight,
  Eye,
  Flag,
  Globe,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  Send,
  Star,
  Trash2,
  Users,
  X,
} from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { relativeTime } from "@/lib/format";
import { REACTIONS, reactionByKey } from "@/lib/reactions";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { mediaService } from "@/services/media";
import {
  backgroundStyle,
  STORY_ERRORS,
  STORY_REPORT_REASONS,
  storiesService,
  type Story,
  type StoryGroup,
  type StoryReportReason,
  type StoryViewer,
} from "@/services/stories";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

import StoryDialog from "./StoryDialog.vue";

// The full-screen story player. Stories advance on a timer (paused while held,
// while a menu or dialog is open, or when the tab is hidden); tapping the
// start half goes back and the end half goes forward, so in Arabic the
// direction follows the reading order, and so do the progress bars and arrow
// keys. Opening a story marks it seen (the server counts each viewer once and
// never the author). The author gets the viewer list; others react or report.
// `canCreate`: the opener can show the create dialog, so the side panel offers it.
const props = withDefaults(
  defineProps<{ groups: StoryGroup[]; startGroup?: number; startStory?: number | null; canCreate?: boolean }>(),
  { startGroup: 0, startStory: null, canCreate: false },
);
const emit = defineEmits<{ close: []; story: [story: Story]; deleted: [id: string]; create: [] }>();
const router = useRouter();
const auth = useAuthStore();

const { t, locale } = useI18n();
const toasts = useToastStore();
const directory = useDirectoryStore();

const DURATION_MS = 6000;
const HOLD_MS = 220;

// A private copy: seen/reaction updates and deletes change it, the parent hears events.
const groups = ref<StoryGroup[]>(JSON.parse(JSON.stringify(props.groups)) as StoryGroup[]);
const firstUnseen = (g: StoryGroup | undefined) => {
  if (!g) return 0;
  const i = g.stories.findIndex((s) => !s.seen);
  return i < 0 ? 0 : i;
};
const gi = ref(Math.min(Math.max(props.startGroup, 0), Math.max(groups.value.length - 1, 0)));
const si = ref(props.startStory ?? firstUnseen(groups.value[gi.value]));

const group = computed(() => groups.value[gi.value]);
const story = computed<Story | undefined>(() => group.value?.stories[si.value]);
const authorName = computed(() => directory.label(group.value?.author_id));
const isRtl = computed(() => locale.value === "ar" || document.documentElement.dir === "rtl");

// ---- playback --------------------------------------------------------------------
const elapsed = ref(0);
const paused = ref(false);
const holding = ref(false);
const ready = ref(false);
const pageHidden = ref(document.visibilityState === "hidden");
const menuOpen = ref(false);
const reportOpen = ref(false);
const viewersOpen = ref(false);
const confirmDelete = ref(false);
const overlayOpen = computed(() => menuOpen.value || reportOpen.value || viewersOpen.value || confirmDelete.value);
// Typing a reply holds the story still.
const replyFocused = ref(false);
const running = computed(
  () => ready.value && !paused.value && !holding.value && !overlayOpen.value && !pageHidden.value && !replyFocused.value,
);

let raf = 0;
let last = 0;
function tick(ts: number) {
  if (running.value && last) {
    elapsed.value += ts - last;
    if (elapsed.value >= DURATION_MS) {
      next();
    }
  }
  last = ts;
  raf = requestAnimationFrame(tick);
}

function progressOf(i: number): number {
  if (i < si.value) return 100;
  if (i > si.value) return 0;
  return Math.min(100, (elapsed.value / DURATION_MS) * 100);
}

function close() {
  emit("close");
}

function next() {
  const g = group.value;
  if (!g) return close();
  if (si.value < g.stories.length - 1) {
    si.value++;
  } else if (gi.value < groups.value.length - 1) {
    gi.value++;
    si.value = firstUnseen(groups.value[gi.value]);
  } else {
    close();
  }
}

function prev() {
  if (si.value > 0) {
    si.value--;
  } else if (gi.value > 0) {
    gi.value--;
    si.value = 0;
  } else {
    elapsed.value = 0;
  }
}

// ---- the current story's photo -----------------------------------------------------
const photoUrl = ref<string | null>(null);
const photoMissing = ref(false);
let loadToken = 0;
// Asked once per story per open viewer (declared before the immediate watch below).
const seenAsked = new Set<string>();

watch(
  () => story.value?.id,
  async () => {
    elapsed.value = 0;
    menuOpen.value = false;
    const s = story.value;
    photoUrl.value = null;
    photoMissing.value = false;
    if (!s) return;
    if (s.kind !== "photo" || !s.media_id) {
      ready.value = true;
    } else {
      ready.value = false;
      const token = ++loadToken;
      const url = await mediaService.resolveUrl(s.media_id);
      if (token !== loadToken) return;
      photoUrl.value = url;
      if (!url) {
        photoMissing.value = true;
        ready.value = true;
      }
    }
    void markSeen(s);
  },
  { immediate: true },
);

function onPhotoLoaded() {
  ready.value = true;
}
function onPhotoError() {
  photoMissing.value = true;
  ready.value = true;
}

function replace(updated: Story) {
  const g = groups.value.find((x) => x.author_id === updated.author_id);
  if (!g) return;
  const i = g.stories.findIndex((s) => s.id === updated.id);
  if (i >= 0) g.stories[i] = updated;
  g.has_unseen = !updated.is_mine && g.stories.some((s) => !s.seen);
  emit("story", updated);
}

async function markSeen(s: Story) {
  if (s.is_mine || s.seen || !s.is_active || seenAsked.has(s.id)) return;
  seenAsked.add(s.id);
  try {
    replace(await storiesService.markSeen(s.id));
  } catch {
    // A story that vanished meanwhile simply stays unseen.
  }
}

// ---- reactions ---------------------------------------------------------------------
const reacting = ref(false);
async function react(key: string) {
  const s = story.value;
  if (!s || reacting.value) return;
  reacting.value = true;
  try {
    replace(s.my_reaction === key ? await storiesService.unreact(s.id) : await storiesService.react(s.id, key));
  } catch (e) {
    toasts.error(e, STORY_ERRORS);
  } finally {
    reacting.value = false;
  }
}

// ---- reply (a direct message to the author) ----------------------------------------
const replyText = ref("");
const replying = ref(false);
async function sendReply() {
  const s = story.value;
  const text = replyText.value.trim();
  if (!s || !text || replying.value) return;
  replying.value = true;
  try {
    const link = new URL(router.resolve(`/stories/${s.id}`).href, window.location.origin).href;
    await storiesService.reply(s, text, t("stories.viewer.replyLink", { link }));
    replyText.value = "";
    toasts.success(t("stories.viewer.replySent"));
  } catch (e) {
    toasts.error(e, STORY_ERRORS);
  } finally {
    replying.value = false;
  }
}

// ---- side panel (wide screens): every author in this viewer ------------------------
const meId = computed(() => auth.account?.id ?? "");
function openGroup(i: number) {
  if (i === gi.value) return;
  gi.value = i;
  si.value = firstUnseen(groups.value[i]);
}
function newCount(g: StoryGroup) {
  return g.author_id === meId.value ? 0 : g.stories.filter((s) => !s.seen).length;
}
function latestAt(g: StoryGroup) {
  return g.stories[g.stories.length - 1]?.created_at ?? "";
}

// ---- delete / report ---------------------------------------------------------------
const deleting = ref(false);
async function doDelete() {
  const s = story.value;
  if (!s || deleting.value) return;
  deleting.value = true;
  try {
    await storiesService.remove(s.id);
    toasts.success(t("stories.viewer.deleted"));
    emit("deleted", s.id);
    confirmDelete.value = false;
    const g = group.value;
    g.stories.splice(si.value, 1);
    if (!g.stories.length) {
      groups.value.splice(gi.value, 1);
      if (!groups.value.length) return close();
      if (gi.value >= groups.value.length) gi.value = groups.value.length - 1;
      si.value = 0;
    } else if (si.value >= g.stories.length) {
      si.value = g.stories.length - 1;
    }
    elapsed.value = 0;
  } catch (e) {
    toasts.error(e, STORY_ERRORS);
  } finally {
    deleting.value = false;
  }
}

const reason = ref<StoryReportReason | null>(null);
const reporting = ref(false);
async function sendReport() {
  const s = story.value;
  if (!s || !reason.value || reporting.value) return;
  reporting.value = true;
  try {
    await storiesService.report(s.id, reason.value);
    toasts.success(t("stories.viewer.reported"));
    reportOpen.value = false;
    reason.value = null;
  } catch (e) {
    toasts.error(e, STORY_ERRORS);
  } finally {
    reporting.value = false;
  }
}

// ---- viewer list (the author's) ----------------------------------------------------
const viewers = ref<StoryViewer[]>([]);
const viewersCursor = ref<string | null>(null);
const viewersMore = ref(false);
const viewersLoading = ref(false);
async function loadViewers(reset = false) {
  const s = story.value;
  if (!s || viewersLoading.value) return;
  viewersLoading.value = true;
  try {
    const page = await storiesService.viewers(s.id, reset ? null : viewersCursor.value);
    viewers.value = reset ? page.data : [...viewers.value, ...page.data];
    viewersCursor.value = page.page?.next_cursor ?? null;
    viewersMore.value = !!page.page?.has_more;
  } catch (e) {
    toasts.error(e, STORY_ERRORS);
  } finally {
    viewersLoading.value = false;
  }
}
function openViewers() {
  viewersOpen.value = true;
  void loadViewers(true);
}

// ---- input -------------------------------------------------------------------------
let downAt = 0;
let holdTimer: number | undefined;
let wasHold = false;
function onPointerDown() {
  downAt = Date.now();
  wasHold = false;
  holdTimer = window.setTimeout(() => {
    holding.value = true;
    wasHold = true;
  }, HOLD_MS);
}
function onPointerUp() {
  window.clearTimeout(holdTimer);
  holding.value = false;
  if (Date.now() - downAt >= HOLD_MS) wasHold = true;
}
function tap(direction: "prev" | "next") {
  if (wasHold) {
    wasHold = false;
    return;
  }
  if (direction === "prev") prev();
  else next();
}

function onKeydown(e: KeyboardEvent) {
  const target = e.target as HTMLElement | null;
  if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) {
    if (e.key === "Escape") target.blur();
    return; // typing a reply: keys are text, not navigation
  }
  if (overlayOpen.value) {
    if (e.key === "Escape" && menuOpen.value) menuOpen.value = false;
    return;
  }
  const forward = isRtl.value ? "ArrowLeft" : "ArrowRight";
  const backward = isRtl.value ? "ArrowRight" : "ArrowLeft";
  if (e.key === "Escape") {
    e.preventDefault();
    close();
  } else if (e.key === forward) {
    e.preventDefault();
    next();
  } else if (e.key === backward) {
    e.preventDefault();
    prev();
  } else if (e.key === " " && !(e.target instanceof HTMLButtonElement)) {
    e.preventDefault();
    paused.value = !paused.value;
  }
}
function onVisibility() {
  pageHidden.value = document.visibilityState === "hidden";
}

const root = ref<HTMLElement | null>(null);
useFocusTrap(root);
let previousOverflow = "";
onMounted(() => {
  previousOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  window.addEventListener("keydown", onKeydown);
  document.addEventListener("visibilitychange", onVisibility);
  raf = requestAnimationFrame(tick);
});
onBeforeUnmount(() => {
  document.body.style.overflow = previousOverflow;
  window.removeEventListener("keydown", onKeydown);
  document.removeEventListener("visibilitychange", onVisibility);
  cancelAnimationFrame(raf);
  window.clearTimeout(holdTimer);
});

const AUDIENCE_ICONS = { public: Globe, friends: Users, close_friends: Star } as const;
const PrevIcon = computed(() => (isRtl.value ? ChevronRight : ChevronLeft));
const NextIcon = computed(() => (isRtl.value ? ChevronLeft : ChevronRight));
const hasPrev = computed(() => si.value > 0 || gi.value > 0);
const hasNext = computed(() => !!group.value && (si.value < group.value.stories.length - 1 || gi.value < groups.value.length - 1));
</script>

<template>
  <Teleport to="body">
    <div
      ref="root"
      role="dialog"
      aria-modal="true"
      :aria-label="t('stories.viewer.label', { name: authorName })"
      tabindex="-1"
      class="fixed inset-0 z-[80] flex items-center justify-center bg-gray-950 text-white"
      data-testid="story-viewer"
    >
      <button
        type="button"
        class="absolute end-3 top-3 z-30 hidden h-10 w-10 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white sm:inline-flex"
        :aria-label="t('stories.viewer.close')"
        data-testid="story-close"
        @click="close"
      >
        <X class="h-6 w-6" aria-hidden="true" />
      </button>

      <!-- Wide screens: every author in this viewer, the current one highlighted. -->
      <aside
        class="hidden h-full w-[22rem] shrink-0 flex-col self-stretch border-e border-white/10 bg-gray-900 lg:flex"
        :aria-label="t('stories.viewer.panel')"
        data-testid="story-panel"
      >
        <p class="px-5 pb-3 pt-5 text-2xl font-extrabold tracking-tight">{{ t("stories.viewer.panelTitle") }}</p>
        <div v-if="canCreate" class="px-3">
          <p class="px-2 pb-2 text-sm font-semibold text-white/70">{{ t("stories.viewer.yourStory") }}</p>
          <button
            type="button"
            class="flex w-full items-center gap-3 rounded-xl px-2 py-2 text-start hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
            data-testid="story-panel-create"
            @click="emit('create')"
          >
            <span class="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-white/10 text-brand-300">
              <Plus class="h-7 w-7" aria-hidden="true" />
            </span>
            <span class="min-w-0">
              <span class="block text-[15px] font-semibold">{{ t("stories.viewer.createStory") }}</span>
              <span class="block truncate text-xs text-white/70">{{ t("stories.viewer.createHint") }}</span>
            </span>
          </button>
        </div>
        <p class="px-5 pb-2 pt-4 text-sm font-semibold text-white/70">{{ t("stories.viewer.panel") }}</p>
        <ul class="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 pb-4">
          <li v-for="(g, i) in groups" :key="g.author_id">
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-xl px-2 py-2 text-start hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
              :class="i === gi && 'bg-white/10'"
              :aria-current="i === gi ? 'true' : undefined"
              :data-author="g.author_id"
              data-testid="story-panel-author"
              @click="openGroup(i)"
            >
              <span
                class="shrink-0 rounded-full p-[3px]"
                :class="g.has_unseen ? 'bg-gradient-to-br from-brand-600 via-brand-400 to-accent-500' : 'bg-white/25'"
              >
                <UserAvatar :name="directory.label(g.author_id)" :media-id="directory.avatarOf(g.author_id)" :size="50" class="ring-2 ring-gray-900" />
              </span>
              <span class="min-w-0">
                <span dir="auto" class="block truncate text-[15px] font-semibold">
                  {{ g.author_id === meId ? t("stories.viewer.yourStory") : directory.label(g.author_id) }}
                </span>
                <span class="block truncate text-xs" :class="newCount(g) ? 'font-semibold text-brand-200' : 'text-white/70'">
                  <template v-if="newCount(g)">{{ t("stories.viewer.newCount", { n: newCount(g) }) }} · </template>{{ latestAt(g) ? relativeTime(latestAt(g)) : "" }}
                </span>
              </span>
            </button>
          </li>
        </ul>
      </aside>

      <div class="flex h-full min-w-0 flex-1 items-center justify-center gap-4 sm:py-4">
        <button
          type="button"
          class="hidden h-12 w-12 shrink-0 items-center justify-center rounded-full bg-white/90 text-gray-900 shadow-pop transition hover:bg-white disabled:invisible sm:inline-flex"
          :disabled="!hasPrev"
          :aria-label="t('stories.viewer.prev')"
          @click="prev"
        >
          <component :is="PrevIcon" class="h-6 w-6" aria-hidden="true" />
        </button>

        <div
          v-if="story && group"
          class="relative h-full w-full overflow-hidden bg-gray-900 sm:aspect-[9/16] sm:h-full sm:max-h-[calc(100vh-2rem)] sm:w-auto sm:rounded-2xl"
          :style="story.kind === 'text' || photoMissing ? { backgroundImage: backgroundStyle(story.background) } : undefined"
          :data-story="story.id"
        >
          <!-- media -->
          <img
            v-if="story.kind === 'photo' && photoUrl"
            :key="story.id"
            :src="photoUrl"
            alt=""
            class="absolute inset-0 h-full w-full object-contain"
            @load="onPhotoLoaded"
            @error="onPhotoError"
          />
          <p
            v-if="story.kind === 'text'"
            dir="auto"
            class="absolute inset-0 flex items-center justify-center whitespace-pre-wrap break-words px-8 text-center text-2xl font-bold leading-snug sm:text-3xl"
            data-testid="story-text-body"
          >
            {{ story.text }}
          </p>
          <p
            v-else-if="story.text"
            dir="auto"
            class="absolute inset-x-0 bottom-24 z-10 px-6 text-center text-base font-semibold drop-shadow-[0_1px_3px_rgba(0,0,0,0.8)]"
          >
            {{ story.text }}
          </p>

          <!-- tap zones: start half back, end half forward -->
          <div class="absolute inset-0 z-10 flex" @pointerdown="onPointerDown" @pointerup="onPointerUp" @pointerleave="onPointerUp" @pointercancel="onPointerUp">
            <button type="button" class="h-full w-1/3 cursor-default focus:outline-none" tabindex="-1" :aria-label="t('stories.viewer.prev')" @click="tap('prev')" />
            <button type="button" class="h-full w-2/3 cursor-default focus:outline-none" tabindex="-1" :aria-label="t('stories.viewer.next')" data-testid="story-tap-next" @click="tap('next')" />
          </div>

          <!-- header: progress, author, controls -->
          <div class="absolute inset-x-0 top-0 z-20 bg-gradient-to-b from-black/60 to-transparent px-3 pb-6 pt-3">
            <div class="flex gap-1" role="presentation" data-testid="story-progress">
              <span
                v-for="(s, i) in group.stories"
                :key="s.id"
                class="relative h-[3px] flex-1 overflow-hidden rounded-full bg-white/35"
              >
                <span class="absolute inset-y-0 start-0 rounded-full bg-white" :style="{ width: `${progressOf(i)}%` }" data-testid="story-progress-fill" />
              </span>
            </div>
            <p class="sr-only" aria-live="polite">{{ t("stories.viewer.progress", { n: si + 1, total: group.stories.length }) }}</p>
            <div class="mt-3 flex items-center gap-2">
              <RouterLink :to="`/u/id/${group.author_id}`" class="flex min-w-0 items-center gap-2 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white">
                <UserAvatar :name="authorName" :media-id="directory.avatarOf(group.author_id)" :size="36" />
                <span dir="auto" class="truncate text-sm font-semibold">{{ authorName }}</span>
              </RouterLink>
              <span class="shrink-0 text-xs text-white/75">{{ relativeTime(story.created_at) }}</span>
              <span class="shrink-0 text-white/75" :title="t('stories.viewer.audience', { audience: t(`stories.create.audiences.${story.audience}`) })">
                <component :is="AUDIENCE_ICONS[story.audience]" class="h-3.5 w-3.5" aria-hidden="true" />
                <span class="sr-only">{{ t("stories.viewer.audience", { audience: t(`stories.create.audiences.${story.audience}`) }) }}</span>
              </span>
              <span v-if="!story.is_active" class="shrink-0 rounded-full bg-white/20 px-2 py-0.5 text-[11px] font-semibold">{{ t("stories.viewer.expired") }}</span>
              <span class="flex-1" />
              <button
                type="button"
                class="inline-flex h-9 w-9 items-center justify-center rounded-full hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
                :aria-label="paused ? t('stories.viewer.play') : t('stories.viewer.pause')"
                :aria-pressed="paused"
                data-testid="story-pause"
                @click="paused = !paused"
              >
                <Play v-if="paused" class="h-5 w-5" fill="currentColor" aria-hidden="true" />
                <Pause v-else class="h-5 w-5" fill="currentColor" aria-hidden="true" />
              </button>
              <div class="relative">
                <button
                  type="button"
                  class="inline-flex h-9 w-9 items-center justify-center rounded-full hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
                  :aria-label="t('stories.viewer.more')"
                  :aria-expanded="menuOpen"
                  aria-haspopup="menu"
                  data-testid="story-more"
                  @click="menuOpen = !menuOpen"
                >
                  <MoreHorizontal class="h-5 w-5" aria-hidden="true" />
                </button>
                <div v-if="menuOpen" class="popover absolute end-0 top-10 z-30 w-56 p-1 text-gray-900 dark:text-gray-100" role="menu">
                  <button
                    v-if="story.is_mine"
                    type="button"
                    role="menuitem"
                    class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm font-semibold text-red-600 hover:bg-gray-100 dark:text-red-400 dark:hover:bg-gray-800"
                    data-testid="story-delete"
                    @click="menuOpen = false; confirmDelete = true"
                  >
                    <Trash2 class="h-4 w-4" aria-hidden="true" />{{ t("stories.viewer.delete") }}
                  </button>
                  <button
                    v-else
                    type="button"
                    role="menuitem"
                    class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm font-semibold hover:bg-gray-100 dark:hover:bg-gray-800"
                    data-testid="story-report"
                    @click="menuOpen = false; reportOpen = true"
                  >
                    <Flag class="h-4 w-4" aria-hidden="true" />{{ t("stories.viewer.report") }}
                  </button>
                </div>
              </div>
              <button
                type="button"
                class="inline-flex h-9 w-9 items-center justify-center rounded-full hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white sm:hidden"
                :aria-label="t('stories.viewer.close')"
                @click="close"
              >
                <X class="h-5 w-5" aria-hidden="true" />
              </button>
            </div>
          </div>

          <!-- footer -->
          <div class="absolute inset-x-0 bottom-0 z-20 bg-gradient-to-t from-black/70 to-transparent px-3 pb-4 pt-10">
            <button
              v-if="story.is_mine"
              type="button"
              class="inline-flex items-center gap-2 rounded-full bg-white/15 px-4 py-2 text-sm font-semibold hover:bg-white/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
              data-testid="story-viewers"
              @click="openViewers"
            >
              <Eye class="h-4 w-4" aria-hidden="true" />
              {{ t("stories.viewer.viewers", { n: story.view_count ?? 0 }, story.view_count ?? 0) }}
              <span v-if="story.reaction_count" class="text-white/80">· {{ story.reaction_count }} {{ t("stories.viewer.reactions") }}</span>
            </button>
            <form
              v-if="!story.is_mine && story.is_active"
              class="mb-3 flex items-center gap-2"
              data-testid="story-reply"
              @submit.prevent="sendReply"
            >
              <label :for="`story-reply-${story.id}`" class="sr-only">{{ t("stories.viewer.replyLabel", { name: authorName }) }}</label>
              <input
                :id="`story-reply-${story.id}`"
                v-model="replyText"
                type="text"
                dir="auto"
                maxlength="1000"
                autocomplete="off"
                class="h-11 min-w-0 flex-1 rounded-full border border-white/50 bg-black/40 px-4 text-sm text-white placeholder:text-white/80 focus:border-white focus:outline-none"
                :placeholder="t('stories.viewer.replyPlaceholder')"
                data-testid="story-reply-input"
                @focus="replyFocused = true"
                @blur="replyFocused = false"
              />
              <button
                type="submit"
                class="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white/15 hover:bg-white/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white disabled:opacity-50"
                :disabled="!replyText.trim() || replying"
                :aria-label="t('stories.viewer.replySend')"
                data-testid="story-reply-send"
              >
                <Send class="h-5 w-5 rtl:-scale-x-100" aria-hidden="true" />
              </button>
            </form>
            <div v-if="!story.is_mine && story.is_active" class="flex items-center justify-center gap-1.5" role="group" :aria-label="t('stories.viewer.reactions')" data-testid="story-reactions">
              <button
                v-for="r in REACTIONS"
                :key="r.key"
                type="button"
                class="inline-flex h-11 w-11 items-center justify-center rounded-full text-2xl transition hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
                :class="story.my_reaction === r.key ? 'bg-white/30 ring-2 ring-white' : 'bg-white/10'"
                :aria-label="story.my_reaction === r.key ? t('stories.viewer.removeReaction') : t('stories.viewer.react', { reaction: t(r.labelKey) })"
                :aria-pressed="story.my_reaction === r.key"
                :disabled="reacting"
                :data-reaction="r.key"
                @click="react(r.key)"
              >
                <span aria-hidden="true">{{ r.emoji }}</span>
              </button>
            </div>
          </div>
        </div>

        <button
          type="button"
          class="hidden h-12 w-12 shrink-0 items-center justify-center rounded-full bg-white/90 text-gray-900 shadow-pop transition hover:bg-white disabled:invisible sm:inline-flex"
          :disabled="!hasNext"
          :aria-label="t('stories.viewer.next')"
          data-testid="story-next"
          @click="next"
        >
          <component :is="NextIcon" class="h-6 w-6" aria-hidden="true" />
        </button>
      </div>

      <StoryDialog inline v-if="confirmDelete" :title="t('stories.viewer.delete')" :close-label="t('stories.closeFriends.close')" @close="confirmDelete = false">
        <p class="text-sm text-gray-700 dark:text-gray-200">{{ t("stories.viewer.deleteConfirm") }}</p>
        <div class="mt-4 flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="confirmDelete = false">{{ t("stories.create.back") }}</button>
          <button type="button" class="btn-danger" :disabled="deleting" data-testid="story-delete-confirm" @click="doDelete">{{ t("stories.viewer.delete") }}</button>
        </div>
      </StoryDialog>

      <StoryDialog inline v-if="reportOpen" :title="t('stories.viewer.reportTitle')" :close-label="t('stories.closeFriends.close')" @close="reportOpen = false">
        <fieldset class="space-y-1 overflow-y-auto text-gray-900 dark:text-gray-100">
          <legend class="mb-2 text-sm text-gray-600 dark:text-gray-300">{{ t("stories.viewer.reportPrompt") }}</legend>
          <label v-for="r in STORY_REPORT_REASONS" :key="r" class="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 hover:bg-gray-100 dark:hover:bg-gray-800">
            <input v-model="reason" type="radio" name="story-report" :value="r" class="h-4 w-4 accent-brand-600" />
            <span class="text-sm">{{ t(`stories.reasons.${r}`) }}</span>
          </label>
        </fieldset>
        <div class="mt-4 flex justify-end">
          <button type="button" class="btn-primary" :disabled="!reason || reporting" data-testid="story-report-send" @click="sendReport">
            {{ t("stories.viewer.reportSend") }}
          </button>
        </div>
      </StoryDialog>

      <StoryDialog inline v-if="viewersOpen" :title="t('stories.viewer.viewersTitle')" :close-label="t('stories.closeFriends.close')" @close="viewersOpen = false">
        <div class="min-h-0 overflow-y-auto text-gray-900 dark:text-gray-100" data-testid="story-viewers-list">
          <p v-if="!viewersLoading && !viewers.length" class="py-6 text-center text-sm text-gray-500 dark:text-gray-400">{{ t("stories.viewer.noViewers") }}</p>
          <ul class="divide-y divide-gray-100 dark:divide-gray-800">
            <li v-for="v in viewers" :key="v.account_id" class="flex items-center gap-3 py-2">
              <RouterLink :to="`/u/id/${v.account_id}`" class="flex min-w-0 flex-1 items-center gap-3">
                <UserAvatar :name="directory.label(v.account_id)" :media-id="directory.avatarOf(v.account_id)" :size="40" />
                <span class="min-w-0">
                  <span dir="auto" class="block truncate text-sm font-semibold">{{ directory.label(v.account_id) }}</span>
                  <span class="block text-xs text-gray-500 dark:text-gray-400">{{ relativeTime(v.viewed_at) }}</span>
                </span>
              </RouterLink>
              <span v-if="reactionByKey(v.reaction)" class="text-xl" :title="t(reactionByKey(v.reaction)!.labelKey)">
                {{ reactionByKey(v.reaction)!.emoji }}
              </span>
            </li>
          </ul>
          <button v-if="viewersMore" type="button" class="btn-ghost mt-2 w-full" :disabled="viewersLoading" @click="loadViewers()">
            {{ t("stories.viewer.loadMore") }}
          </button>
        </div>
      </StoryDialog>
    </div>
  </Teleport>
</template>
