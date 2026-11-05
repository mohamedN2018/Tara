<script setup lang="ts">
// /reels and /reels/:id (roadmap 5.8): the For you and Following reels feeds in
// a full-height vertical pager. The URL follows the reel on screen, so a link
// opens that reel; ?author= keeps the pager on one profile's or Page's reels
// (their Reels tab); ?sheet=comments|share|more opens a sheet over the reel;
// ?create=1 opens "Create reel". Likes, comments and shares are the post's.
import { Bookmark, BookmarkMinus, Clapperboard, Copy, EyeOff, Flag, Plus, Trash2 } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { type LocationQuery, useRoute, useRouter } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import CommentList from "@/components/post/CommentList.vue";
import ShareBox from "@/components/post/ShareBox.vue";
import CreateReelDialog from "@/components/reels/CreateReelDialog.vue";
import ReelPager from "@/components/reels/ReelPager.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import StoryDialog from "@/components/stories/StoryDialog.vue";
import { postService, REPORT_ERRORS } from "@/services/post";
import { REEL_ERRORS, REEL_TABS, type Reel, type ReelTab, reelsService } from "@/services/reels";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";
import type { CursorPage, Post } from "@/types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const toasts = useToastStore();

const reels = ref<Reel[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const failed = ref(false);
const startIndex = ref(0);
const activeIndex = ref(0);
const watched = new Set<string>();

const tab = computed<ReelTab>(() => (REEL_TABS.includes(route.query.tab as ReelTab) ? (route.query.tab as ReelTab) : "for_you"));
const author = computed(() => (typeof route.query.author === "string" ? route.query.author : ""));
const sheet = computed(() => (typeof route.query.sheet === "string" ? route.query.sheet : ""));
const creating = computed(() => route.query.create === "1");
const current = computed(() => reels.value[activeIndex.value] ?? null);
const isOwn = computed(() => !!current.value && current.value.author_id === auth.account?.id);

function fetchPage(next: string | null): Promise<CursorPage<Reel>> {
  return author.value ? reelsService.byAuthor(author.value, next) : reelsService.feed(tab.value, next);
}

function merge(list: Reel[], extra: Reel[]): Reel[] {
  const seen = new Set(list.map((r) => r.id));
  return [...list, ...extra.filter((r) => !seen.has(r.id))];
}

/** (Re)load the list for the current tab or author, starting at the reel in the URL. */
async function load() {
  loading.value = true;
  failed.value = false;
  const wanted = typeof route.params.id === "string" ? route.params.id : "";
  try {
    let list: Reel[] = [];
    let next: string | null = null;
    let more = false;
    // A page can come back short (each item is checked after paging): follow the
    // cursor a little, and for an author's reels until the chosen one is in.
    for (let i = 0; i < 5; i += 1) {
      const page = await fetchPage(next);
      list = merge(list, page.data);
      next = page.page.next_cursor;
      more = page.page.has_more;
      const found = !wanted || !author.value || list.some((r) => r.id === wanted);
      if (!more || (found && list.length >= 3)) break;
    }
    let index = wanted ? list.findIndex((r) => r.id === wanted) : 0;
    if (wanted && index < 0) {
      list = [await reelsService.get(wanted), ...list.filter((r) => r.id !== wanted)];
      index = 0;
    }
    reels.value = list;
    cursor.value = next;
    hasMore.value = more;
    startIndex.value = Math.max(0, index);
    activeIndex.value = startIndex.value;
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response?.status;
    if (status === 404 && wanted) {
      // A reel you may not see: show the feed without it.
      await router.replace({ name: "reels", query: { ...route.query } });
      return;
    }
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

async function loadMore() {
  if (loadingMore.value || !hasMore.value) return;
  loadingMore.value = true;
  try {
    const page = await fetchPage(cursor.value);
    reels.value = merge(reels.value, page.data);
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch {
    // The next scroll near the end asks again.
  } finally {
    loadingMore.value = false;
  }
}

/** The current query without one key. */
function without(key: string): LocationQuery {
  const query = { ...route.query };
  delete query[key];
  return query;
}

// The URL follows the reel on screen, without reloading the list.
let ownId = "";
function onActive(index: number) {
  activeIndex.value = index;
  const reel = reels.value[index];
  if (!reel || route.params.id === reel.id) return;
  ownId = reel.id;
  void router.replace({ name: "reel", params: { id: reel.id }, query: without("sheet") });
}

watch(
  () => [route.name, route.params.id, tab.value, author.value] as const,
  ([name, id], previous) => {
    if (name !== "reels" && name !== "reel") return;
    const [, prevId, prevTab, prevAuthor] = previous ?? [];
    if (id && id === ownId && tab.value === prevTab && author.value === prevAuthor) return;
    if (prevId !== undefined && id === prevId && tab.value === prevTab && author.value === prevAuthor) return;
    void load();
  },
);
onMounted(load);

function setTab(next: ReelTab) {
  void router.push({ name: "reels", query: next === "for_you" ? {} : { tab: next } });
}

function openSheet(name: "comments" | "share" | "more", reel: Reel) {
  const index = reels.value.findIndex((r) => r.id === reel.id);
  if (index >= 0) activeIndex.value = index;
  void router.push({ name: "reel", params: { id: reel.id }, query: { ...route.query, sheet: name } });
}
function closeSheet() {
  void router.replace({ query: without("sheet") });
}

function patch(id: string, changes: Partial<Reel>) {
  reels.value = reels.value.map((r) => (r.id === id ? ({ ...r, ...changes } as Reel) : r));
}

async function like(reel: Reel) {
  if (reel.my_reaction) return;
  patch(reel.id, { my_reaction: "like", reaction_count: reel.reaction_count + 1 });
  try {
    await postService.react(reel.id, "like");
  } catch (err) {
    patch(reel.id, { my_reaction: null, reaction_count: reel.reaction_count });
    toasts.error(err);
  }
}
async function unlike(reel: Reel) {
  patch(reel.id, { my_reaction: null, reaction_count: Math.max(0, reel.reaction_count - 1) });
  try {
    await postService.unreact(reel.id);
  } catch (err) {
    patch(reel.id, { my_reaction: reel.my_reaction, reaction_count: reel.reaction_count });
    toasts.error(err);
  }
}

async function onWatched(reel: Reel, watchMs: number) {
  if (watched.has(reel.id)) return;
  watched.add(reel.id);
  try {
    const { view_count } = await reelsService.view(reel.id, watchMs);
    patch(reel.id, { reel: { ...reel.reel, view_count, viewed_today: true } });
  } catch {
    // A view is best effort.
  }
}

function link(reel: Reel): string {
  return new URL(router.resolve({ name: "reel", params: { id: reel.id } }).href, window.location.origin).toString();
}
async function copyLink(reel: Reel) {
  try {
    await navigator.clipboard.writeText(link(reel));
    toasts.success(t("reels.linkCopied"));
  } catch {
    toasts.push({ text: t("reels.copyFailed"), icon: "error" });
  }
}

function removeFromList(id: string) {
  const index = reels.value.findIndex((r) => r.id === id);
  reels.value = reels.value.filter((r) => r.id !== id);
  activeIndex.value = Math.min(Math.max(0, index), Math.max(0, reels.value.length - 1));
  startIndex.value = activeIndex.value;
}

async function notInterested(reel: Reel) {
  try {
    await reelsService.hide(reel.id);
    closeSheet();
    const index = reels.value.findIndex((r) => r.id === reel.id);
    const list = `${tab.value}|${author.value}`;
    removeFromList(reel.id);
    toasts.push(
      {
        text: t("reels.hidden"),
        icon: "success",
        action: { label: t("reels.undo"), run: () => void undoNotInterested(reel, index, list), testid: "reel-undo-hide" },
      },
      8000,
    );
  } catch (err) {
    toasts.error(err, REEL_ERRORS);
  }
}

/** "Undo" on the toast: the server forgets the mark and the reel comes back where it was. */
async function undoNotInterested(reel: Reel, index: number, list: string) {
  try {
    await reelsService.unhide(reel.id);
    // Put it back only in the list it left (another tab reloads it from the server).
    if (list === `${tab.value}|${author.value}` && !reels.value.some((r) => r.id === reel.id)) {
      const at = Math.min(Math.max(0, index), reels.value.length);
      reels.value = [...reels.value.slice(0, at), reel, ...reels.value.slice(at)];
      activeIndex.value = at;
      startIndex.value = at;
    }
    toasts.success(t("reels.restored"));
  } catch (err) {
    toasts.error(err, REEL_ERRORS);
  }
}

// Save / unsave: the post's saved items (the same service as a post's menu).
async function toggleSave(reel: Reel) {
  const next = !reel.is_saved;
  patch(reel.id, { is_saved: next });
  try {
    if (next) await postService.save(reel.id);
    else await postService.unsave(reel.id);
    closeSheet();
    toasts.success(t(next ? "reels.savedToast" : "reels.unsavedToast"));
  } catch (err) {
    patch(reel.id, { is_saved: !next });
    toasts.error(err);
  }
}

// Report: the post's report flow (moderation reviews it as any post).
const reporting = ref(false);
const reportReason = ref("");
const reportBusy = ref(false);
watch(sheet, () => {
  reporting.value = false;
  reportReason.value = "";
});
async function submitReport(reel: Reel) {
  const reason = reportReason.value.trim();
  if (!reason || reportBusy.value) return;
  reportBusy.value = true;
  try {
    await postService.report(reel.id, reason);
    closeSheet();
    toasts.success(t("reels.reportSent"));
  } catch (err) {
    toasts.error(err, REPORT_ERRORS);
  } finally {
    reportBusy.value = false;
  }
}

async function removeReel(reel: Reel) {
  if (!window.confirm(t("reels.confirmDelete"))) return;
  try {
    await postService.remove(reel.id);
    closeSheet();
    removeFromList(reel.id);
    toasts.success(t("reels.deleted"));
  } catch (err) {
    toasts.error(err);
  }
}

function onShared(_post: Post) {
  if (current.value) patch(current.value.id, { share_count: current.value.share_count + 1 });
  toasts.success(t("reels.shared"));
  closeSheet();
}

function closeCreate() {
  void router.replace({ query: without("create") });
}
function onCreated(reel: Reel) {
  void router.push({ name: "reel", params: { id: reel.id } });
}
function onPostedVideo(post: Post) {
  void router.push({ name: "post", params: { id: post.id } });
}
</script>

<template>
  <AppShell :left="false" :right="false">
    <div class="mx-auto flex w-full max-w-[1100px] flex-col" data-testid="reels-view">
      <div class="mb-2 flex items-center gap-2">
        <h1 class="me-2 flex items-center gap-2 text-xl font-bold">
          <Clapperboard class="h-6 w-6 text-accent-600 dark:text-accent-300" aria-hidden="true" />{{ t("reels.title") }}
        </h1>
        <nav v-if="!author" class="flex gap-1" role="tablist" :aria-label="t('reels.tabs.label')">
          <button
            v-for="x in REEL_TABS"
            :key="x"
            type="button"
            role="tab"
            :aria-selected="tab === x"
            class="rounded-full px-3 py-1.5 text-sm font-semibold transition"
            :class="tab === x ? 'bg-brand-100 text-brand-700 dark:bg-brand-950 dark:text-brand-200' : 'text-gray-600 hover:bg-gray-200 dark:text-gray-300 dark:hover:bg-gray-800'"
            :data-testid="`reels-tab-${x}`"
            @click="setTab(x)"
          >
            {{ t(`reels.tabs.${x}`) }}
          </button>
        </nav>
        <RouterLink :to="{ query: { ...route.query, create: '1' } }" class="btn-primary ms-auto text-sm" data-testid="reels-create">
          <Plus class="h-4 w-4" aria-hidden="true" /> {{ t("reels.create.title") }}
        </RouterLink>
      </div>

      <div class="h-[calc(100dvh-14rem)] min-h-[22rem] lg:h-[calc(100dvh-9.5rem)]">
        <div v-if="loading" class="flex h-full items-center justify-center" role="status">
          <span class="h-8 w-8 animate-spin rounded-full border-4 border-brand-500 border-t-transparent" aria-hidden="true" />
          <span class="sr-only">{{ t("states.loading") }}</span>
        </div>
        <ErrorState v-else-if="failed" :message="t('reels.loadFailed')" @retry="load" />
        <EmptyState v-else-if="!reels.length" class="card" data-testid="reels-empty">
          {{ author ? t("reels.empty.author") : t(`reels.empty.${tab}`) }}
        </EmptyState>
        <ReelPager
          v-else
          :reels="reels"
          :start-index="startIndex"
          :has-more="hasMore"
          @active="onActive"
          @more="loadMore"
          @like="like"
          @unlike="unlike"
          @comments="openSheet('comments', $event)"
          @share="openSheet('share', $event)"
          @menu="openSheet('more', $event)"
          @watched="onWatched"
        />
      </div>
    </div>

    <StoryDialog v-if="sheet === 'comments' && current" :title="t('reels.commentsTitle')" :close-label="t('reels.close')" @close="closeSheet">
      <div class="min-h-0 overflow-y-auto" data-testid="reel-comments-sheet">
        <CommentList
          :post-id="current.id"
          :post-author-id="current.author_id"
          :policy="current.comment_policy"
          @total="patch(current.id, { comment_count: $event })"
          @added="patch(current.id, { comment_count: current.comment_count + 1 })"
        />
      </div>
    </StoryDialog>

    <StoryDialog v-if="sheet === 'share' && current" :title="t('reels.shareTitle')" :close-label="t('reels.close')" @close="closeSheet">
      <div class="space-y-3" data-testid="reel-share-sheet">
        <button type="button" class="btn-outline w-full" data-testid="reel-copy-link" @click="copyLink(current)">
          <Copy class="h-4 w-4" aria-hidden="true" /> {{ t("reels.copyLink") }}
        </button>
        <ShareBox :post="current" @cancel="closeSheet" @shared="onShared" />
      </div>
    </StoryDialog>

    <StoryDialog v-if="sheet === 'more' && current" :title="t('reels.moreTitle')" :close-label="t('reels.close')" @close="closeSheet">
      <form v-if="reporting" class="space-y-3" data-testid="reel-report-form" @submit.prevent="submitReport(current)">
        <label for="reel-report-reason" class="block text-sm font-medium">{{ t("reels.reportReason") }}</label>
        <textarea id="reel-report-reason" v-model="reportReason" class="input min-h-20" rows="3" dir="auto" maxlength="500" data-testid="reel-report-reason" />
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="reporting = false">{{ t("reels.reportCancel") }}</button>
          <button type="submit" class="btn-primary" :disabled="!reportReason.trim() || reportBusy" data-testid="reel-report-submit">{{ t("reels.reportSubmit") }}</button>
        </div>
      </form>
      <div v-else class="space-y-1" data-testid="reel-more-sheet">
        <button
          type="button"
          class="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-start hover:bg-gray-100 dark:hover:bg-gray-800"
          :aria-pressed="!!current.is_saved"
          data-testid="reel-save"
          @click="toggleSave(current)"
        >
          <BookmarkMinus v-if="current.is_saved" class="h-5 w-5 shrink-0" aria-hidden="true" />
          <Bookmark v-else class="h-5 w-5 shrink-0" aria-hidden="true" />
          <span>
            <span class="block font-semibold">{{ current.is_saved ? t("reels.unsave") : t("reels.save") }}</span>
            <span v-if="!current.is_saved" class="block text-xs text-gray-600 dark:text-gray-300">{{ t("reels.saveHint") }}</span>
          </span>
        </button>
        <button v-if="!isOwn" type="button" class="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-start hover:bg-gray-100 dark:hover:bg-gray-800" data-testid="reel-not-interested" @click="notInterested(current)">
          <EyeOff class="h-5 w-5 shrink-0" aria-hidden="true" />
          <span>
            <span class="block font-semibold">{{ t("reels.notInterested") }}</span>
            <span class="block text-xs text-gray-600 dark:text-gray-300">{{ t("reels.notInterestedHint") }}</span>
          </span>
        </button>
        <button type="button" class="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-start font-semibold hover:bg-gray-100 dark:hover:bg-gray-800" @click="copyLink(current)">
          <Copy class="h-5 w-5 shrink-0" aria-hidden="true" /> {{ t("reels.copyLink") }}
        </button>
        <button v-if="!isOwn" type="button" class="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-start hover:bg-gray-100 dark:hover:bg-gray-800" data-testid="reel-report" @click="reporting = true">
          <Flag class="h-5 w-5 shrink-0" aria-hidden="true" />
          <span>
            <span class="block font-semibold">{{ t("reels.report") }}</span>
            <span class="block text-xs text-gray-600 dark:text-gray-300">{{ t("reels.reportHint") }}</span>
          </span>
        </button>
        <button v-if="isOwn" type="button" class="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-start font-semibold text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40" data-testid="reel-delete" @click="removeReel(current)">
          <Trash2 class="h-5 w-5 shrink-0" aria-hidden="true" /> {{ t("reels.delete") }}
        </button>
      </div>
    </StoryDialog>

    <CreateReelDialog v-if="creating" @close="closeCreate" @created="onCreated" @posted-video="onPostedVideo" />
  </AppShell>
</template>
