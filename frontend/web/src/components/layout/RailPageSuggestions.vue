<script setup lang="ts">
import { Check, Plus, X } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { graphService } from "@/services/graph";
import { type PageSuggestion, relationshipsService } from "@/services/relationships";
import { useToastStore } from "@/stores/toasts";

import { MAX_RAIL_PAGES, railHeading, railSection } from "./rightRail";

// "Suggested pages": the most followed published pages the viewer doesn't
// follow yet. Hidden when there are none.
const { t } = useI18n();
const toasts = useToastStore();
const pages = ref<PageSuggestion[]>([]);
const followed = ref<Record<string, true>>({});
const busy = ref("");
const lastRemoved = ref<{ page: PageSuggestion; index: number } | null>(null);

async function load() {
  pages.value = await relationshipsService.pages(MAX_RAIL_PAGES).catch(() => []);
}

async function follow(page: PageSuggestion) {
  if (busy.value) return;
  busy.value = page.page_id;
  try {
    await graphService.followPage(page.page_id);
    followed.value = { ...followed.value, [page.page_id]: true };
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = "";
  }
}

async function dismiss(page: PageSuggestion) {
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
  <section v-if="pages.length || lastRemoved" :class="railSection" aria-labelledby="rs-pages" data-testid="rail-pages">
    <h2 id="rs-pages" :class="railHeading">{{ t("suggestions.pages") }}</h2>
    <p v-if="lastRemoved" class="mb-1 flex items-center justify-between gap-2 rounded-xl bg-gray-100 px-3 py-2 text-sm dark:bg-gray-800" role="status">
      <span>{{ t("people.pageSuggestions.removed") }}</span>
      <button type="button" class="font-semibold text-brand-600 hover:underline dark:text-brand-300" :disabled="!!busy" data-testid="rail-page-undo" @click="undo">
        {{ t("people.pageSuggestions.undo") }}
      </button>
    </p>
    <ul class="space-y-1">
      <li
        v-for="p in pages"
        :key="p.page_id"
        class="flex items-center gap-3 rounded-xl p-2 transition hover:bg-gray-200/60 dark:hover:bg-gray-800/60"
        data-testid="rail-page"
      >
        <RouterLink :to="{ name: 'page', params: { handle: p.handle } }" class="shrink-0" tabindex="-1" aria-hidden="true">
          <UserAvatar :name="p.name" :media-id="p.avatar_media_id" :size="40" />
        </RouterLink>
        <div class="min-w-0 flex-1">
          <RouterLink
            :to="{ name: 'page', params: { handle: p.handle } }"
            class="block truncate text-sm font-semibold hover:underline"
            dir="auto"
          >
            {{ p.name }}
          </RouterLink>
          <p class="truncate text-xs text-gray-600 dark:text-gray-400">
            <span v-if="p.category" dir="auto">{{ p.category }} · </span>{{ t("suggestions.followers", p.followers_count + (followed[p.page_id] ? 1 : 0)) }}
          </p>
        </div>
        <button
          v-if="!followed[p.page_id]"
          type="button"
          class="btn shrink-0 bg-brand-50 px-3 py-1.5 text-brand-700 hover:bg-brand-100 dark:bg-brand-900/40 dark:text-brand-200 dark:hover:bg-brand-900/60"
          :disabled="busy === p.page_id"
          :aria-label="t('suggestions.followLabel', { name: p.name })"
          data-testid="rail-page-follow"
          @click="follow(p)"
        >
          <Plus class="h-4 w-4" aria-hidden="true" /> {{ t("suggestions.follow") }}
        </button>
        <span v-else class="flex shrink-0 items-center gap-1 px-2 text-sm font-medium text-gray-600 dark:text-gray-300" role="status" data-testid="rail-page-followed">
          <Check class="h-4 w-4" aria-hidden="true" /> {{ t("suggestions.followed") }}
        </span>
        <button
          v-if="!followed[p.page_id]"
          type="button"
          class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-gray-500 hover:bg-gray-200 dark:hover:bg-gray-700"
          :disabled="busy === p.page_id"
          :aria-label="t('people.pageSuggestions.remove', { name: p.name })"
          data-testid="rail-page-dismiss"
          @click="dismiss(p)"
        >
          <X class="h-4 w-4" aria-hidden="true" />
        </button>
      </li>
    </ul>
  </section>
</template>
