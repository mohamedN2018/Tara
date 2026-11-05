<script setup lang="ts">
import { ImagePlus, PenSquare } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import ManagePageRail from "@/components/pages/ManagePageRail.vue";
import PageAbout from "@/components/pages/PageAbout.vue";
import PageEditDialog from "@/components/pages/PageEditDialog.vue";
import PageHeader, { type PageTab } from "@/components/pages/PageHeader.vue";
import PageLinksCard from "@/components/pages/PageLinksCard.vue";
import PagePhotosCard from "@/components/pages/PagePhotosCard.vue";
import PagePostComposer from "@/components/pages/PagePostComposer.vue";
import PageTransparencyDialog from "@/components/pages/PageTransparencyDialog.vue";
import PageTeam from "@/components/pages/PageTeam.vue";
import PostCard from "@/components/post/PostCard.vue";
import ReelGrid from "@/components/reels/ReelGrid.vue";
import ReportDialog from "@/components/social/ReportDialog.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { httpStatus } from "@/lib/api";
import { mediaService } from "@/services/media";
import { canEditPage, canModeratePosts, canPostAs, type Page, pageService } from "@/services/pages";
import { usePageDirectoryStore } from "@/stores/pageDirectory";
import { useToastStore } from "@/stores/toasts";
import type { Post } from "@/types";
import NotFoundView from "@/views/NotFoundView.vue";

// /pages/:handle — a page as its visitors and its team see it: the header
// (cover, avatar, follow, edit, "..." menu), then Posts (intro card + the page's
// timeline, with "Create post" for owners, admins and editors), About and,
// for the team, Team. Hidden and missing pages are a 404.
const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const toasts = useToastStore();
const pageDirectory = usePageDirectoryStore();

const page = ref<Page | null>(null);
const loading = ref(true);
const missing = ref(false);
const error = ref(false);

const isTab = (v: unknown): v is PageTab => v === "posts" || v === "about" || v === "reels" || v === "team";
const tab = computed<PageTab>(() => {
  const wanted = route.query.tab;
  if (!isTab(wanted) || (wanted === "team" && !page.value?.my_role)) return "posts";
  return wanted;
});
function setTab(next: PageTab) {
  router.replace({ query: { ...route.query, tab: next === "posts" ? undefined : next } });
}

async function load() {
  loading.value = true;
  missing.value = false;
  error.value = false;
  try {
    const p = await pageService.get(String(route.params.handle));
    page.value = p;
    pageDirectory.remember(p);
    void loadSaved();
    void loadPosts(true);
    if (route.query.edit === "1") {
      if (canEditPage(p)) editing.value = true;
      router.replace({ query: { ...route.query, edit: undefined } });
    }
  } catch (e) {
    if (httpStatus(e) === 404) missing.value = true;
    else error.value = true;
  } finally {
    loading.value = false;
  }
}

// ---- timeline ----
const posts = ref<Post[]>([]);
const postsCursor = ref<string | null>(null);
const postsLoading = ref(false);
const postsError = ref(false);
async function loadPosts(reset = false) {
  if (!page.value || (postsLoading.value && !reset)) return;
  postsLoading.value = true;
  postsError.value = false;
  try {
    const res = await pageService.posts(page.value.id, reset ? null : postsCursor.value);
    posts.value = reset ? res.data : [...posts.value, ...res.data];
    postsCursor.value = res.page.next_cursor;
  } catch {
    postsError.value = true;
  } finally {
    postsLoading.value = false;
  }
}
function posted(post: Post) {
  posts.value = [post, ...posts.value];
  setTab("posts");
}
function removed(id: string) {
  posts.value = posts.value.filter((p) => p.id !== id);
}

// ---- follow ----
function followChanged(following: boolean) {
  if (!page.value) return;
  const count = page.value.followers_count;
  page.value = {
    ...page.value,
    viewer_following: following,
    followers_count: count === null ? null : Math.max(0, count + (following ? 1 : -1)),
  };
}
async function unfollow() {
  if (!page.value) return;
  try {
    await pageService.unfollow(page.value.id);
    followChanged(false);
    toasts.success(t("pageHub.header.unfollowed", { name: page.value.name }));
  } catch (e) {
    toasts.error(e);
  }
}

// ---- saved (null: unknown, the menu hides the item) ----
const saved = ref<boolean | null>(null);
async function loadSaved() {
  if (!page.value) return;
  try {
    saved.value = await pageService.isSaved(page.value.id);
  } catch {
    saved.value = null;
  }
}
async function toggleSave() {
  if (!page.value || saved.value === null) return;
  const next = !saved.value;
  saved.value = next;
  try {
    if (next) await pageService.save(page.value.id);
    else await pageService.unsave(page.value.id);
    toasts.success(t(next ? "pageHub.header.savedToast" : "pageHub.header.unsavedToast"));
  } catch (e) {
    saved.value = !next;
    toasts.error(e);
  }
}

async function copyLink() {
  if (!page.value) return;
  try {
    await navigator.clipboard.writeText(new URL(`/pages/${page.value.handle}`, window.location.origin).href);
    toasts.success(t("pageHub.header.copied"));
  } catch {
    toasts.push({ text: t("errors.copyFailed"), icon: "error" });
  }
}

// ---- photos (editors and up; the server checks the media are theirs) ----
const busyPhoto = ref<"" | "avatar" | "cover">("");
async function setPhoto(kind: "avatar" | "cover", file: File | null) {
  if (!page.value || busyPhoto.value) return;
  busyPhoto.value = kind;
  try {
    const id = file ? (await mediaService.upload(file, "image")).id : null;
    page.value = await pageService.update(page.value.id, kind === "avatar" ? { avatar_media_id: id } : { cover_media_id: id });
    pageDirectory.remember(page.value);
    toasts.success(t("pageHub.header.imageUpdated"));
  } catch (e) {
    toasts.error(e);
  } finally {
    busyPhoto.value = "";
  }
}

const editing = ref(false);
const composing = ref(false);
const reporting = ref(false);
const transparency = ref(false);
function edited(p: Page) {
  page.value = p;
  pageDirectory.remember(p);
}

watch(
  () => route.params.handle,
  (handle) => {
    if (!handle) return;
    page.value = null;
    posts.value = [];
    saved.value = null;
    load();
  },
  { immediate: true },
);
</script>

<template>
  <NotFoundView v-if="missing" />
  <AppShell v-else :left="false" :right="false">
    <div class="mx-auto -mt-4 w-full max-w-[1250px] space-y-4">
      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error || !page" @retry="load" />
      <template v-else>
        <PageHeader
          :page="page"
          :tab="tab"
          :saved="saved"
          :busy-photo="busyPhoto"
          @update:tab="setTab"
          @follow="followChanged"
          @edit="editing = true"
          @compose="composing = true"
          @photo="setPhoto"
          @copy="copyLink"
          @save="toggleSave"
          @report="reporting = true"
          @unfollow="unfollow"
          @transparency="transparency = true"
        />

        <div id="page-panel" role="tabpanel" :aria-labelledby="`page-tab-${tab}`" class="mx-auto w-full max-w-[1100px]">
          <div v-if="tab === 'posts'" class="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
            <div class="space-y-4 lg:sticky lg:top-20 lg:self-start">
              <!-- The team's shortcuts first (plan 08), then the intro, photos and links. -->
              <ManagePageRail :page="page" @settings="editing = true" @transparency="transparency = true" />
              <PageAbout :page="page" links-apart />
              <PagePhotosCard :page="page" />
              <PageLinksCard :page="page" />
            </div>
            <div class="min-w-0 space-y-4">
              <div v-if="canPostAs(page)" class="card flex items-center gap-3 p-3" data-testid="page-composer-card">
                <UserAvatar :name="page.name" :media-id="page.avatar_media_id" :size="40" />
                <button
                  type="button"
                  class="min-w-0 flex-1 truncate rounded-full bg-gray-100 px-4 py-2.5 text-start text-gray-500 transition hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700"
                  dir="auto"
                  @click="composing = true"
                >
                  {{ t("pageHub.posts.whatsNew", { name: page.name }) }}
                </button>
                <button type="button" class="icon-btn text-emerald-600" :aria-label="t('pageHub.posts.addPhotos')" @click="composing = true">
                  <ImagePlus class="h-5 w-5" aria-hidden="true" />
                </button>
              </div>
              <p v-else-if="canEditPage(page) && page.status !== 'published'" class="card p-3 text-sm text-amber-700 dark:text-amber-300">
                {{ t("pageHub.posts.draftPage") }}
              </p>

              <h2 class="sr-only">{{ t("pageHub.tabs.posts") }}</h2>
              <LoadingSkeleton v-if="postsLoading && !posts.length" :rows="2" />
              <ErrorState v-else-if="postsError && !posts.length" @retry="loadPosts(true)" />
              <EmptyState v-else-if="!posts.length">
                {{ canPostAs(page) ? t("pageHub.posts.emptyStaff") : t("pageHub.posts.empty") }}
                <template v-if="canPostAs(page)" #action>
                  <button type="button" class="btn-primary" @click="composing = true">
                    <PenSquare class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.card.createPost") }}
                  </button>
                </template>
              </EmptyState>
              <PostCard
                v-for="p in posts"
                :key="p.id"
                :post="p"
                :author-name="page.name"
                :author-avatar="page.avatar_media_id"
                :page-moderator="canModeratePosts(page)"
                :page-editor="canPostAs(page)"
                @removed="removed"
              />
              <button v-if="postsCursor" type="button" class="btn-ghost mx-auto block" :disabled="postsLoading" @click="loadPosts()">
                {{ postsLoading ? t("states.loading") : t("states.loadMore") }}
              </button>
            </div>
          </div>
          <div v-else-if="tab === 'about'" class="mx-auto max-w-[760px]">
            <PageAbout :page="page" full />
          </div>
          <div v-else-if="tab === 'reels'" class="mx-auto max-w-[760px]">
            <ReelGrid :author-id="page.id" />
          </div>
          <div v-else-if="tab === 'team'" class="mx-auto max-w-[760px]">
            <PageTeam :page="page" />
          </div>
        </div>
      </template>
    </div>

    <PageEditDialog v-if="editing && page" :page="page" @close="editing = false" @saved="edited" />
    <PagePostComposer v-if="composing && page" :page="page" @close="composing = false" @posted="posted" />
    <ReportDialog v-if="reporting && page" target-type="page" :target-id="page.id" :name="page.name" @close="reporting = false" />
    <PageTransparencyDialog v-if="transparency && page" :page="page" @close="transparency = false" />
  </AppShell>
</template>
