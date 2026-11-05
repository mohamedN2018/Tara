<script setup lang="ts">
import { Check, Plus, X } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { pageCategoryLabel } from "@/lib/pageCategory";
import { pageService } from "@/services/pages";
import { type PageSuggestion, relationshipsService } from "@/services/relationships";
import { useToastStore } from "@/stores/toasts";

// "Suggested for you" on the Pages manager's Discover tab: graph's suggested
// pages (published, live, most followed, not followed, owned or dismissed by
// the viewer), as a row of cards with Follow and Remove. Hidden when graph has
// none or cannot answer; nothing is made up.
const MAX = 12;

const i18n = useI18n();
const { t } = i18n;
const toasts = useToastStore();
const pages = ref<PageSuggestion[]>([]);
const followed = ref<Record<string, true>>({});
const busy = ref("");
const lastRemoved = ref<{ page: PageSuggestion; index: number } | null>(null);

async function load() {
  pages.value = await relationshipsService.pages(MAX).catch(() => []);
}

async function follow(page: PageSuggestion) {
  if (busy.value) return;
  busy.value = page.page_id;
  try {
    await pageService.follow(page.page_id);
    followed.value = { ...followed.value, [page.page_id]: true };
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = "";
  }
}

async function remove(page: PageSuggestion) {
  if (busy.value) return;
  busy.value = page.page_id;
  try {
    await relationshipsService.dismiss(page.page_id, "page");
    lastRemoved.value = { page, index: pages.value.findIndex((p) => p.page_id === page.page_id) };
    pages.value = pages.value.filter((p) => p.page_id !== page.page_id);
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = "";
  }
}

async function undo() {
  const removed = lastRemoved.value;
  if (!removed || busy.value) return;
  busy.value = removed.page.page_id;
  try {
    await relationshipsService.undismiss(removed.page.page_id, "page");
    const next = [...pages.value];
    next.splice(Math.max(removed.index, 0), 0, removed.page);
    pages.value = next;
    lastRemoved.value = null;
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = "";
  }
}

onMounted(load);
</script>

<template>
  <section v-if="pages.length || lastRemoved" class="card p-4" aria-labelledby="pages-suggested-title" data-testid="pages-suggested">
    <div class="mb-3">
      <h2 id="pages-suggested-title" class="text-lg font-bold">{{ t("pageHub.suggested.title") }}</h2>
      <p class="text-sm text-gray-500 dark:text-gray-400">{{ t("pageHub.suggested.hint") }}</p>
    </div>
    <p
      v-if="lastRemoved"
      class="mb-3 flex items-center justify-between gap-2 rounded-xl bg-gray-100 px-3 py-2 text-sm dark:bg-gray-800"
      role="status"
    >
      <span>{{ t("pageHub.suggested.removed", { name: lastRemoved.page.name }) }}</span>
      <button
        type="button"
        class="font-semibold text-brand-600 hover:underline dark:text-brand-300"
        :disabled="!!busy"
        data-testid="pages-suggested-undo"
        @click="undo"
      >
        {{ t("pageHub.suggested.undo") }}
      </button>
    </p>
    <ul v-if="pages.length" class="-mx-1 flex snap-x gap-3 overflow-x-auto px-1 pb-2" data-testid="pages-suggested-list">
      <li
        v-for="p in pages"
        :key="p.page_id"
        class="relative flex w-44 shrink-0 snap-start flex-col overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900"
        data-testid="pages-suggested-item"
      >
        <button
          v-if="!followed[p.page_id]"
          type="button"
          class="absolute end-2 top-2 z-10 flex h-8 w-8 items-center justify-center rounded-full bg-gray-900/60 text-white hover:bg-gray-900/80"
          :disabled="busy === p.page_id"
          :aria-label="t('pageHub.suggested.removeLabel', { name: p.name })"
          :title="t('pageHub.suggested.remove')"
          data-testid="pages-suggested-remove"
          @click="remove(p)"
        >
          <X class="h-4 w-4" aria-hidden="true" />
        </button>
        <RouterLink
          :to="{ name: 'page', params: { handle: p.handle } }"
          class="flex aspect-square items-center justify-center bg-tara-gradient"
          tabindex="-1"
          aria-hidden="true"
        >
          <span class="rounded-full border-4 border-white bg-white dark:border-gray-900 dark:bg-gray-900">
            <UserAvatar :name="p.name" :media-id="p.avatar_media_id" :size="96" />
          </span>
        </RouterLink>
        <div class="flex flex-1 flex-col gap-2 p-3">
          <div class="min-w-0">
            <RouterLink
              :to="{ name: 'page', params: { handle: p.handle } }"
              class="block truncate font-semibold hover:underline"
              data-testid="pages-suggested-name"
            >
              <bdi>{{ p.name }}</bdi>
            </RouterLink>
            <p class="truncate text-xs text-gray-500 dark:text-gray-400">
              <template v-if="p.category"><bdi>{{ pageCategoryLabel(p.category, i18n) }}</bdi> · </template>
              {{ t("pageHub.card.followers", { count: p.followers_count + (followed[p.page_id] ? 1 : 0) }, p.followers_count + (followed[p.page_id] ? 1 : 0)) }}
            </p>
          </div>
          <button
            v-if="!followed[p.page_id]"
            type="button"
            class="btn mt-auto w-full bg-brand-50 py-1.5 text-brand-700 hover:bg-brand-100 dark:bg-brand-900/40 dark:text-brand-200 dark:hover:bg-brand-900/60"
            :disabled="busy === p.page_id"
            :aria-label="t('pageHub.suggested.followLabel', { name: p.name })"
            data-testid="pages-suggested-follow"
            @click="follow(p)"
          >
            <Plus class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.suggested.follow") }}
          </button>
          <span
            v-else
            class="mt-auto flex w-full items-center justify-center gap-1 rounded-lg bg-gray-100 py-1.5 text-sm font-semibold text-gray-700 dark:bg-gray-800 dark:text-gray-200"
            role="status"
            data-testid="pages-suggested-followed"
          >
            <Check class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.suggested.followed") }}
          </span>
        </div>
      </li>
    </ul>
  </section>
</template>
