<script setup lang="ts">
// The optional topic picker after sign-up (Tara Intelligence WP 6.6, owner decision 11):
// real topics from feed's taxonomy (`GET /feed/topics/`), at most 10 picks, and Skip.
// The picks become the account's own explicit topics (`POST /feed/preferences/onboarding/`).
// Sensitive topics are not offered here; they can be added later in My Algorithm.
import { Check, Search } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { type FeedTopic, feedService } from "@/services/feed";
import { useToastStore } from "@/stores/toasts";

const MAX = 10;
const emit = defineEmits<{ done: [skipped: boolean] }>();

const { t, locale } = useI18n();
const toasts = useToastStore();
const topics = ref<FeedTopic[]>([]);
const picked = ref<string[]>([]);
const known = ref<Record<string, FeedTopic>>({});
const q = ref("");
const loading = ref(true);
const failed = ref(false);
const busy = ref(false);

const label = (tp: FeedTopic) => (locale.value === "ar" ? tp.label_ar : tp.label_en) || tp.slug;
const full = computed(() => picked.value.length >= MAX);

async function load(query = "") {
  loading.value = true;
  failed.value = false;
  try {
    const rows = (await feedService.topics(query, 60)).filter((tp) => !tp.sensitive);
    topics.value = rows;
    for (const tp of rows) known.value[tp.slug] = tp;
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}

let timer: ReturnType<typeof setTimeout> | undefined;
watch(q, (value) => {
  clearTimeout(timer);
  timer = setTimeout(() => void load(value.trim()), 250);
});

function toggle(slug: string) {
  if (picked.value.includes(slug)) picked.value = picked.value.filter((s) => s !== slug);
  else if (!full.value) picked.value = [...picked.value, slug];
}

async function finish(skipped: boolean) {
  if (busy.value) return;
  busy.value = true;
  try {
    await feedService.onboarding(skipped ? [] : picked.value, skipped);
    emit("done", skipped);
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

onMounted(() => load());
</script>

<template>
  <section class="card p-5 sm:p-6" aria-labelledby="onboarding-title" data-testid="onboarding-topics">
    <h1 id="onboarding-title" class="text-2xl font-bold">{{ t("myAlgorithm.onboarding.title") }}</h1>
    <p class="mt-1 text-sm text-gray-600 dark:text-gray-300">{{ t("myAlgorithm.onboarding.hint") }}</p>

    <label class="relative mt-4 block">
      <span class="sr-only">{{ t("myAlgorithm.onboarding.search") }}</span>
      <Search class="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden="true" />
      <input v-model="q" type="search" class="input ps-9" dir="auto" :placeholder="t('myAlgorithm.onboarding.search')" data-testid="onboarding-search" />
    </label>

    <p class="mt-3 text-sm font-semibold" role="status" aria-live="polite" data-testid="onboarding-count">
      {{ t("myAlgorithm.onboarding.picked", { count: picked.length }) }}
      <span v-if="full" class="ms-1 font-normal text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.onboarding.max") }}</span>
    </p>

    <p v-if="loading && !topics.length" class="mt-3 text-sm text-gray-500 dark:text-gray-400" role="status">{{ t("states.loading") }}</p>
    <p v-else-if="failed" class="mt-3 text-sm text-red-600 dark:text-red-400" role="alert">
      {{ t("myAlgorithm.onboarding.failed") }}
      <button type="button" class="ms-2 font-semibold underline" @click="load(q.trim())">{{ t("states.retry") }}</button>
    </p>
    <p v-else-if="!topics.length" class="mt-3 text-sm text-gray-500 dark:text-gray-400" data-testid="onboarding-empty">{{ t("myAlgorithm.onboarding.empty") }}</p>
    <ul v-else class="mt-3 flex flex-wrap gap-2" data-testid="onboarding-list">
      <li v-for="tp in topics" :key="tp.slug">
        <button
          type="button"
          class="chip"
          :class="picked.includes(tp.slug) ? 'chip-active' : ''"
          :aria-pressed="picked.includes(tp.slug)"
          :disabled="!picked.includes(tp.slug) && full"
          :data-testid="`onboarding-topic-${tp.slug}`"
          @click="toggle(tp.slug)"
        >
          <Check v-if="picked.includes(tp.slug)" class="h-4 w-4" aria-hidden="true" />
          <span dir="auto">{{ label(tp) }}</span>
        </button>
      </li>
    </ul>

    <div class="mt-6 flex flex-wrap items-center justify-end gap-2">
      <button type="button" class="btn-ghost" :disabled="busy" data-testid="onboarding-skip" @click="finish(true)">{{ t("myAlgorithm.onboarding.skip") }}</button>
      <button type="button" class="btn-gradient" :disabled="busy || !picked.length" data-testid="onboarding-done" @click="finish(false)">
        {{ t("myAlgorithm.onboarding.done") }}
      </button>
    </div>
  </section>
</template>
