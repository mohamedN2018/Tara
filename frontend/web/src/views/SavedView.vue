<script setup lang="ts">
import { Bookmark, FolderInput, FolderOpen, MoreHorizontal, Pencil, Plus, ShoppingBag, Trash2 } from "lucide-vue-next";
import { computed, nextTick, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AppShell from "@/components/layout/AppShell.vue";
import MarketplaceCard from "@/components/marketplace/MarketplaceCard.vue";
import PostCard from "@/components/post/PostCard.vue";
import SaveToCollection from "@/components/post/SaveToCollection.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { marketplaceService } from "@/services/marketplace";
import { postService, type SavedCollection } from "@/services/post";
import { useToastStore } from "@/stores/toasts";
import type { Listing, Post } from "@/types";

// Saved (reference layout): a start column with "All saved items", the
// listings and "My collections" (+ Create new collection); the main column shows
// the chosen one. Collections are the owner's own (the server 404s anyone else).
const { t } = useI18n();
const toasts = useToastStore();

/** "all" | "listings" | a collection id. */
const view = ref<string>("all");
const collections = ref<SavedCollection[]>([]);
const defaultCollection = computed(() => collections.value.find((c) => c.is_default) ?? null);
const own = computed(() => collections.value.filter((c) => !c.is_default));
const selected = computed(() => collections.value.find((c) => c.id === view.value) ?? null);
const label = (c: SavedCollection) => (c.is_default ? t("postsFeed.saved.defaultName") : c.name);

const posts = ref<Post[]>([]);
const savedIds = ref<Record<string, string>>({});
const collectionIds = ref<Record<string, string>>({});
const listings = ref<Listing[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
let generation = 0;

async function loadCollections() {
  try {
    collections.value = await postService.collections();
  } catch {
    // The column still offers "All saved items".
  }
}

async function fetchPage(more: boolean) {
  const at = more ? (cursor.value ?? undefined) : undefined;
  if (view.value === "listings") {
    const page = await marketplaceService.savedList(at);
    listings.value = more ? [...listings.value, ...page.data] : page.data;
    cursor.value = page.page.next_cursor;
    return;
  }
  const page = await postService.savedPage(at, view.value === "all" ? null : view.value);
  posts.value = more ? [...posts.value, ...page.posts] : page.posts;
  savedIds.value = more ? { ...savedIds.value, ...page.savedIds } : page.savedIds;
  collectionIds.value = more ? { ...collectionIds.value, ...page.collectionIds } : page.collectionIds;
  cursor.value = page.nextCursor;
}

async function load() {
  const run = ++generation;
  loading.value = true;
  error.value = false;
  try {
    await fetchPage(false);
  } catch {
    if (run === generation) error.value = true;
  } finally {
    if (run === generation) loading.value = false;
  }
}

async function loadMore() {
  if (!cursor.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    await fetchPage(true);
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

function choose(next: string) {
  if (view.value === next) return;
  view.value = next;
  closeMenus();
  void load();
}

function collectionName(id: string | undefined): string {
  const c = collections.value.find((x) => x.id === id);
  return c ? label(c) : "";
}

// ---- create / rename / delete ----
const dialog = ref<null | "create" | "rename" | "delete">(null);
const nameDraft = ref("");
const busy = ref(false);
const nameInput = ref<HTMLInputElement | null>(null);
const optionsOpen = ref(false);
useEscapeKey(optionsOpen, () => (optionsOpen.value = false));
useEscapeKey(
  computed(() => dialog.value !== null),
  () => (dialog.value = null),
);

function closeMenus() {
  optionsOpen.value = false;
}
async function openDialog(kind: "create" | "rename" | "delete") {
  closeMenus();
  nameDraft.value = kind === "rename" && selected.value ? selected.value.name : "";
  dialog.value = kind;
  await nextTick();
  nameInput.value?.focus();
}

async function submitName() {
  const name = nameDraft.value.trim();
  if (!name || busy.value) return;
  busy.value = true;
  try {
    if (dialog.value === "create") {
      const c = await postService.createCollection(name);
      collections.value = [...collections.value, c];
      toasts.success(t("postsFeed.saved.created", { name: c.name }));
      dialog.value = null;
      choose(c.id);
    } else if (dialog.value === "rename" && selected.value) {
      const c = await postService.renameCollection(selected.value.id, name);
      collections.value = collections.value.map((x) => (x.id === c.id ? { ...x, name: c.name } : x));
      toasts.success(t("postsFeed.saved.renamed"));
      dialog.value = null;
    }
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

async function confirmDelete() {
  const c = selected.value;
  if (!c || busy.value) return;
  busy.value = true;
  try {
    await postService.deleteCollection(c.id);
    dialog.value = null;
    toasts.success(t("postsFeed.saved.deleted"));
    await loadCollections();
    choose("all");
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

// ---- move one saved post ----
const moving = ref<Post | null>(null);
function onMoved(c: SavedCollection) {
  const post = moving.value;
  if (!post) return;
  const before = collectionIds.value[post.id];
  collectionIds.value = { ...collectionIds.value, [post.id]: c.id };
  collections.value = collections.value.map((x) =>
    x.id === c.id ? { ...x, item_count: x.item_count + 1 } : x.id === before ? { ...x, item_count: Math.max(0, x.item_count - 1) } : x,
  );
  // In a collection view, a post moved elsewhere leaves this list.
  if (view.value !== "all" && c.id !== view.value) posts.value = posts.value.filter((p) => p.id !== post.id);
}
function onUnsaved(id: string) {
  posts.value = posts.value.filter((p) => p.id !== id);
  void loadCollections();
}

const title = computed(() => {
  if (view.value === "all") return t("postsFeed.saved.all");
  if (view.value === "listings") return t("saved.tabListings");
  return selected.value ? label(selected.value) : t("saved.title");
});

onMounted(() => {
  void loadCollections();
  void load();
});

const navRow =
  "flex w-full items-center gap-3 rounded-xl px-2 py-2 text-start text-[15px] font-semibold transition hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:hover:bg-gray-800";
const navActive = "bg-brand-50 text-brand-700 dark:bg-brand-950/60 dark:text-brand-200";
</script>

<template>
  <AppShell :left="false" :right="false">
    <div class="mx-auto flex w-full max-w-[1100px] flex-col gap-4 lg:flex-row lg:items-start">
      <!-- Start column: saved navigation -->
      <aside class="card w-full shrink-0 p-3 lg:sticky lg:top-20 lg:w-80" :aria-label="t('saved.title')" data-testid="saved-nav">
        <h1 class="px-2 pb-2 text-2xl font-bold">{{ t("saved.title") }}</h1>
        <ul class="space-y-0.5">
          <li>
            <button type="button" :class="[navRow, view === 'all' ? navActive : '']" :aria-current="view === 'all' ? 'page' : undefined" data-testid="saved-all" @click="choose('all')">
              <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white"><Bookmark class="h-5 w-5" aria-hidden="true" /></span>
              {{ t("postsFeed.saved.all") }}
            </button>
          </li>
          <li>
            <button type="button" :class="[navRow, view === 'listings' ? navActive : '']" :aria-current="view === 'listings' ? 'page' : undefined" data-testid="saved-listings" @click="choose('listings')">
              <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-100 text-accent-700 dark:bg-accent-900/40 dark:text-accent-300"><ShoppingBag class="h-5 w-5" aria-hidden="true" /></span>
              {{ t("saved.tabListings") }}
            </button>
          </li>
        </ul>

        <div class="mt-3 border-t border-gray-100 pt-3 dark:border-gray-800">
          <h2 class="px-2 pb-1 text-[15px] font-semibold text-gray-500 dark:text-gray-400">{{ t("postsFeed.saved.collections") }}</h2>
          <ul class="space-y-0.5" data-testid="saved-collections">
            <li v-if="defaultCollection">
              <button type="button" :class="[navRow, view === defaultCollection.id ? navActive : '']" :aria-current="view === defaultCollection.id ? 'page' : undefined" @click="choose(defaultCollection.id)">
                <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gray-200 dark:bg-gray-800"><FolderOpen class="h-5 w-5" aria-hidden="true" /></span>
                <span class="min-w-0 flex-1 truncate">{{ label(defaultCollection) }}</span>
                <span class="text-xs font-normal text-gray-500 dark:text-gray-400">{{ defaultCollection.item_count }}</span>
              </button>
            </li>
            <li v-for="c in own" :key="c.id">
              <button type="button" :class="[navRow, view === c.id ? navActive : '']" :aria-current="view === c.id ? 'page' : undefined" data-testid="saved-collection" @click="choose(c.id)">
                <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-100 text-brand-700 dark:bg-brand-950/70 dark:text-brand-300"><FolderOpen class="h-5 w-5" aria-hidden="true" /></span>
                <span class="min-w-0 flex-1 truncate" dir="auto">{{ c.name }}</span>
                <span class="text-xs font-normal text-gray-500 dark:text-gray-400">{{ c.item_count }}</span>
              </button>
            </li>
          </ul>
          <button type="button" class="btn-primary mt-3 w-full justify-center" data-testid="saved-create" @click="openDialog('create')">
            <Plus class="h-5 w-5" aria-hidden="true" /> {{ t("postsFeed.saved.create") }}
          </button>
        </div>
      </aside>

      <!-- Main column -->
      <section class="min-w-0 flex-1 space-y-4 lg:max-w-[680px]" aria-labelledby="saved-title">
        <header class="flex items-center gap-2 px-1">
          <h2 id="saved-title" class="min-w-0 flex-1 truncate text-xl font-bold" dir="auto" data-testid="saved-title">{{ title }}</h2>
          <div v-if="selected && !selected.is_default" class="relative">
            <button
              type="button"
              class="icon-btn"
              :aria-label="t('postsFeed.saved.options', { name: selected.name })"
              :aria-expanded="optionsOpen"
              data-testid="collection-options"
              @click="optionsOpen = !optionsOpen"
            >
              <MoreHorizontal class="h-5 w-5" aria-hidden="true" />
            </button>
            <template v-if="optionsOpen">
              <div class="fixed inset-0 z-40" aria-hidden="true" @click="optionsOpen = false" />
              <div class="popover absolute end-0 z-50 mt-1 w-56 p-1.5" role="group">
                <button type="button" class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-start text-sm font-medium hover:bg-gray-100 dark:hover:bg-gray-800" data-testid="collection-rename" @click="openDialog('rename')">
                  <Pencil class="h-5 w-5" aria-hidden="true" /> {{ t("postsFeed.saved.rename") }}
                </button>
                <button type="button" class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-start text-sm font-medium text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40" data-testid="collection-delete" @click="openDialog('delete')">
                  <Trash2 class="h-5 w-5" aria-hidden="true" /> {{ t("postsFeed.saved.delete") }}
                </button>
              </div>
            </template>
          </div>
        </header>

        <LoadingSkeleton v-if="loading" :rows="3" />
        <ErrorState v-else-if="error" @retry="load" />
        <template v-else-if="view === 'listings'">
          <EmptyState v-if="listings.length === 0" class="card">{{ t("market.noSaved") }}</EmptyState>
          <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <MarketplaceCard v-for="l in listings" :key="l.id" :listing="l" />
          </div>
        </template>
        <template v-else>
          <EmptyState v-if="posts.length === 0" class="card">{{ view === "all" ? t("saved.empty") : t("postsFeed.saved.emptyCollection") }}</EmptyState>
          <div v-for="p in posts" :key="p.id" class="space-y-1" data-testid="saved-item">
            <div class="flex items-center gap-2 px-1 text-xs text-gray-500 dark:text-gray-400">
              <FolderOpen class="h-4 w-4" aria-hidden="true" />
              <span class="min-w-0 flex-1 truncate" dir="auto">{{ collectionName(collectionIds[p.id]) }}</span>
              <button
                v-if="savedIds[p.id]"
                type="button"
                class="inline-flex items-center gap-1 rounded-md px-2 py-1 font-semibold text-brand-600 hover:bg-brand-50 dark:text-brand-300 dark:hover:bg-brand-950/60"
                data-testid="saved-move"
                @click="moving = p"
              >
                <FolderInput class="h-4 w-4" aria-hidden="true" /> {{ t("postsFeed.saved.move") }}
              </button>
            </div>
            <PostCard :post="p" @unsaved="onUnsaved" @removed="onUnsaved" />
          </div>
        </template>
        <button v-if="!loading && !error && cursor" class="btn-ghost mx-auto block" :disabled="loadingMore" @click="loadMore">
          {{ loadingMore ? t("states.loading") : t("states.loadMore") }}
        </button>
      </section>
    </div>

    <SaveToCollection
      v-if="moving"
      :post-id="moving.id"
      :saved-id="savedIds[moving.id]"
      :current-id="collectionIds[moving.id]"
      @done="onMoved"
      @close="moving = null"
    />

    <!-- Create / rename / delete -->
    <Teleport to="body">
      <div v-if="dialog" class="fixed inset-0 z-[60] flex items-center justify-center p-4">
        <div class="absolute inset-0 bg-black/50" aria-hidden="true" @click="dialog = null" />
        <div
          class="card relative w-full max-w-md p-5"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="'saved-dialog-title'"
          data-testid="saved-dialog"
        >
          <template v-if="dialog === 'delete'">
            <h2 id="saved-dialog-title" class="text-lg font-bold">{{ t("postsFeed.saved.delete") }}</h2>
            <p class="mt-2 text-sm" dir="auto">{{ t("postsFeed.saved.deleteConfirm", { name: selected?.name ?? "" }) }}</p>
            <div class="mt-4 flex justify-end gap-2">
              <button type="button" class="btn-ghost" @click="dialog = null">{{ t("postsFeed.saved.cancel") }}</button>
              <button type="button" class="btn-primary bg-red-600 hover:bg-red-700" :disabled="busy" data-testid="saved-delete-confirm" @click="confirmDelete">
                {{ t("postsFeed.saved.deleteButton") }}
              </button>
            </div>
          </template>
          <form v-else @submit.prevent="submitName">
            <h2 id="saved-dialog-title" class="text-lg font-bold">
              {{ dialog === "create" ? t("postsFeed.saved.createTitle") : t("postsFeed.saved.renameTitle") }}
            </h2>
            <label for="saved-name" class="mt-3 block text-sm font-medium">{{ t("postsFeed.saved.name") }}</label>
            <input
              id="saved-name"
              ref="nameInput"
              v-model="nameDraft"
              class="input mt-1"
              maxlength="80"
              dir="auto"
              :placeholder="t('postsFeed.saved.namePlaceholder')"
              data-testid="saved-name"
            />
            <div class="mt-4 flex justify-end gap-2">
              <button type="button" class="btn-ghost" @click="dialog = null">{{ t("postsFeed.saved.cancel") }}</button>
              <button type="submit" class="btn-primary" :disabled="busy || !nameDraft.trim()" data-testid="saved-name-submit">
                {{ dialog === "create" ? t("postsFeed.saved.createButton") : t("postsFeed.saved.renameButton") }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>
  </AppShell>
</template>
