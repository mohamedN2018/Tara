<script setup lang="ts">
// "Your interests" in My Algorithm (Tara Intelligence WP 6.4, 8.5-B2): every row the
// server holds, grouped by tier, with the counts it stored by event type (the viewer's
// own activity, never item ids). Edit makes an explicit choice; Remove deletes the row
// (an inferred one stays suppressed). The picker adds topics from `GET /feed/topics/`.
import { Plus, Search, Trash2 } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { type FeedTopic, feedService, type InterestPolarity, type InterestProfile, type InterestRow, INTEREST_TIERS, type InterestTier } from "@/services/feed";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

const props = defineProps<{ profile: InterestProfile }>();
const emit = defineEmits<{ changed: [] }>();

const { t, te, locale } = useI18n();
const directory = useDirectoryStore();
const toasts = useToastStore();
const busy = ref<string | null>(null);

const groups = computed(() =>
  INTEREST_TIERS.map((tier) => ({ tier, rows: props.profile.tiers?.[tier] ?? [] })).filter((g) => g.rows.length),
);

function label(row: InterestRow): string {
  const own = locale.value === "ar" ? row.label_ar : row.label_en;
  if (own) return own;
  if (row.dim === "creator") return directory.label(row.key);
  return row.label_en || row.label_ar || row.key;
}

function eventLabel(key: string): string {
  const path = `myAlgorithm.page.interests.events.${key}`;
  return te(path) ? t(path) : t("myAlgorithm.page.interests.events.other");
}
/** Server counts, largest first; only positive integers are shown. */
function counts(row: InterestRow): { key: string; n: number }[] {
  return Object.entries(row.counts ?? {})
    .filter(([, n]) => Number.isInteger(n) && n > 0)
    .map(([key, n]) => ({ key, n }))
    .sort((a, b) => b.n - a.n);
}
function polarityLabel(p?: string): string | null {
  const path = `myAlgorithm.page.interests.polarity.${p}`;
  return p && te(path) ? t(path) : null;
}

const rowKey = (row: InterestRow) => `${row.dim}:${row.key}`;

async function choose(row: InterestRow, polarity: InterestPolarity) {
  if (busy.value) return;
  busy.value = rowKey(row);
  try {
    await feedService.setInterest(row.key, polarity);
    toasts.success(t("myAlgorithm.toast.saved"));
    emit("changed");
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = null;
  }
}

async function remove(row: InterestRow) {
  if (busy.value) return;
  busy.value = rowKey(row);
  try {
    await feedService.deleteInterest(row.dim, row.key);
    toasts.success(t("myAlgorithm.page.interests.removed"));
    emit("changed");
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = null;
  }
}

// ---- the topic picker ----
const picking = ref(false);
const q = ref("");
const found = ref<FeedTopic[]>([]);
const searching = ref(false);
let timer: ReturnType<typeof setTimeout> | undefined;
async function search(value: string) {
  searching.value = true;
  try {
    found.value = await feedService.topics(value, 20);
  } catch {
    found.value = [];
  } finally {
    searching.value = false;
  }
}
watch(q, (value) => {
  clearTimeout(timer);
  timer = setTimeout(() => void search(value.trim()), 250);
});
watch(picking, (open) => open && void search(q.value.trim()));
const topicLabel = (tp: FeedTopic) => (locale.value === "ar" ? tp.label_ar : tp.label_en) || tp.slug;

async function add(tp: FeedTopic, polarity: InterestPolarity) {
  if (busy.value) return;
  busy.value = `topic:${tp.slug}`;
  try {
    await feedService.setInterest(tp.slug, polarity);
    toasts.success(t("myAlgorithm.page.interests.added"));
    emit("changed");
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = null;
  }
}

const tierTitle = (tier: InterestTier) => t(`myAlgorithm.page.interests.tiers.${tier}`);
</script>

<template>
  <div data-testid="interest-profile">
    <p v-if="!groups.length" class="mt-3 text-sm text-gray-500 dark:text-gray-400" data-testid="interests-empty">{{ t("myAlgorithm.page.interests.empty") }}</p>
    <div v-for="g in groups" :key="g.tier" class="mt-4" :data-testid="`interest-tier-${g.tier}`">
      <h3 class="text-sm font-bold text-gray-700 dark:text-gray-200">{{ tierTitle(g.tier) }}</h3>
      <ul class="mt-1 divide-y divide-gray-100 dark:divide-gray-800">
        <li v-for="row in g.rows" :key="rowKey(row)" class="flex flex-wrap items-center gap-x-3 gap-y-1 py-2" data-testid="interest-row">
          <div class="min-w-0 flex-1">
            <p class="flex flex-wrap items-center gap-2 text-sm font-semibold">
              <bdi dir="auto">{{ label(row) }}</bdi>
              <span v-if="polarityLabel(row.polarity)" class="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600 dark:bg-gray-800 dark:text-gray-300">
                {{ polarityLabel(row.polarity) }}
              </span>
            </p>
            <p v-if="counts(row).length" class="mt-0.5 text-xs text-gray-500 dark:text-gray-400" data-testid="interest-counts">
              <span v-for="(c, i) in counts(row)" :key="c.key"><template v-if="i"> · </template>{{ t("myAlgorithm.page.interests.count", { label: eventLabel(c.key), count: c.n }) }}</span>
            </p>
          </div>
          <div class="flex shrink-0 flex-wrap gap-1">
            <template v-if="row.dim === 'topic'">
              <button v-if="row.polarity !== 'like'" type="button" class="btn-ghost px-2 py-1 text-xs" :disabled="busy === rowKey(row)" data-testid="interest-like" @click="choose(row, 'like')">
                {{ t("myAlgorithm.page.interests.like") }}
              </button>
              <button v-if="row.polarity !== 'dislike'" type="button" class="btn-ghost px-2 py-1 text-xs" :disabled="busy === rowKey(row)" data-testid="interest-dislike" @click="choose(row, 'dislike')">
                {{ t("myAlgorithm.page.interests.dislike") }}
              </button>
            </template>
            <button type="button" class="btn-ghost px-2 py-1 text-xs text-red-600 dark:text-red-400" :disabled="busy === rowKey(row)" :aria-label="`${t('myAlgorithm.page.interests.remove')} ${label(row)}`" data-testid="interest-remove" @click="remove(row)">
              <Trash2 class="h-4 w-4" aria-hidden="true" /> {{ t("myAlgorithm.page.interests.remove") }}
            </button>
          </div>
        </li>
      </ul>
    </div>

    <div class="mt-4">
      <button v-if="!picking" type="button" class="btn-soft" data-testid="interest-add" @click="picking = true">
        <Plus class="h-4 w-4" aria-hidden="true" /> {{ t("myAlgorithm.page.interests.add") }}
      </button>
      <div v-else class="rounded-xl border border-gray-200 p-3 dark:border-gray-800" data-testid="topic-picker">
        <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.interests.addHint") }}</p>
        <label class="relative mt-2 block">
          <span class="sr-only">{{ t("myAlgorithm.page.interests.search") }}</span>
          <Search class="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden="true" />
          <input v-model="q" type="search" class="input ps-9" dir="auto" :placeholder="t('myAlgorithm.page.interests.search')" data-testid="topic-search" />
        </label>
        <p v-if="searching && !found.length" class="mt-2 text-sm text-gray-500 dark:text-gray-400" role="status">{{ t("states.loading") }}</p>
        <p v-else-if="!found.length" class="mt-2 text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.interests.noMatch") }}</p>
        <ul v-else class="mt-2 max-h-64 divide-y divide-gray-100 overflow-y-auto dark:divide-gray-800">
          <li v-for="tp in found" :key="tp.slug" class="flex items-center gap-2 py-1.5" data-testid="topic-option">
            <bdi class="min-w-0 flex-1 truncate text-sm" dir="auto">{{ topicLabel(tp) }}</bdi>
            <button type="button" class="btn-ghost px-2 py-1 text-xs" :disabled="!!busy" :data-testid="`topic-like-${tp.slug}`" @click="add(tp, 'like')">{{ t("myAlgorithm.page.interests.like") }}</button>
            <button type="button" class="btn-ghost px-2 py-1 text-xs" :disabled="!!busy" :data-testid="`topic-mute-${tp.slug}`" @click="add(tp, 'muted')">{{ t("myAlgorithm.page.interests.mute") }}</button>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>
