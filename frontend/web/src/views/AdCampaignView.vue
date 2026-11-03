<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { type AdSet, adsService, type Campaign, type CampaignReport } from "@/services/ads";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const route = useRoute();
const toasts = useToastStore();
const id = computed(() => route.params.id as string);

const campaign = ref<Campaign | null>(null);
const report = ref<CampaignReport | null>(null);
const adSets = ref<AdSet[]>([]);
const loading = ref(true);
const error = ref(false);
const busy = ref(false);

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const [campaigns, stats, sets] = await Promise.all([
      adsService.campaigns(),
      adsService.report(id.value),
      adsService.adSets(id.value),
    ]);
    campaign.value = campaigns.find((c) => c.id === id.value) ?? null;
    report.value = stats;
    adSets.value = sets;
    if (!campaign.value) error.value = true;
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

const statsFor = (creativeId: string) => report.value?.creatives.find((c) => c.id === creativeId);

async function toggle() {
  if (!campaign.value || busy.value) return;
  busy.value = true;
  try {
    const next = campaign.value.status === "active" ? "paused" : "active";
    campaign.value = await adsService.setStatus(campaign.value.id, next);
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

const newSet = ref({ name: "", placement: "feed", cpc: "0.10", cpm: "1.00" });
async function addAdSet() {
  if (busy.value) return;
  busy.value = true;
  try {
    await adsService.createAdSet(id.value, { ...newSet.value, name: newSet.value.name.trim() });
    newSet.value.name = "";
    adSets.value = await adsService.adSets(id.value);
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

const drafts = ref<Record<string, { headline: string; body: string; cta: string; link_url: string }>>({});
function draftFor(adSetId: string) {
  drafts.value[adSetId] ??= { headline: "", body: "", cta: t("ads.defaultCta"), link_url: "" };
  return drafts.value[adSetId];
}
async function addCreative(adSetId: string) {
  if (busy.value) return;
  busy.value = true;
  try {
    await adsService.createCreative(adSetId, draftFor(adSetId));
    delete drafts.value[adSetId];
    adSets.value = await adsService.adSets(id.value);
    report.value = await adsService.report(id.value);
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[720px] space-y-4">
      <RouterLink to="/ads" class="text-sm text-brand-600 hover:underline dark:text-brand-300">{{ t("ads.title") }}</RouterLink>
      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error || !campaign" @retry="load" />
      <template v-else>
        <section class="card p-4">
          <div class="flex items-center justify-between gap-3">
            <h1 class="min-w-0 truncate text-xl font-bold" dir="auto">{{ campaign.name }}</h1>
            <span class="rounded-full bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-800">{{ t(`ads.status.${campaign.status}`) }}</span>
            <button v-if="campaign.status !== 'completed'" class="btn-ghost text-sm" :disabled="busy" @click="toggle">
              {{ campaign.status === "active" ? t("ads.pause") : t("ads.resume") }}
            </button>
          </div>
          <dl v-if="report" class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="campaign-stats">
            <div><dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("ads.spent") }}</dt><dd class="font-semibold" dir="ltr">{{ report.spent }} / {{ report.budget }}</dd></div>
            <div><dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("ads.impressions") }}</dt><dd class="font-semibold">{{ report.impressions }}</dd></div>
            <div><dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("ads.clicks") }}</dt><dd class="font-semibold">{{ report.clicks }}</dd></div>
            <div><dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("ads.ctr") }}</dt><dd class="font-semibold" dir="ltr">{{ (report.ctr * 100).toFixed(1) }}%</dd></div>
          </dl>
        </section>

        <section v-for="set in adSets" :key="set.id" class="card p-4" data-testid="ad-set">
          <h2 class="font-semibold" dir="auto">{{ set.name || t("ads.adSet") }}</h2>
          <p class="text-xs text-gray-500 dark:text-gray-400" dir="ltr">{{ t(`ads.placements.${set.placement}`) }} · CPC {{ set.cpc }} · CPM {{ set.cpm }}</p>
          <ul class="mt-3 space-y-2">
            <li v-for="c in set.creatives" :key="c.id" class="rounded-lg border border-gray-100 p-3 text-sm dark:border-gray-800" data-testid="creative">
              <span class="flex items-center justify-between gap-2">
                <span class="min-w-0 truncate font-medium" dir="auto">{{ c.headline }}</span>
                <span class="shrink-0 text-xs text-gray-500 dark:text-gray-400">{{ t(`ads.review.${c.review_status}`) }}</span>
              </span>
              <span v-if="statsFor(c.id)" class="block text-xs text-gray-500 dark:text-gray-400">
                {{ t("ads.impressions") }}: {{ statsFor(c.id)?.impressions }} · {{ t("ads.clicks") }}: {{ statsFor(c.id)?.clicks }}
              </span>
            </li>
          </ul>
          <form class="mt-3 space-y-2 border-t border-gray-100 pt-3 dark:border-gray-800" @submit.prevent="addCreative(set.id)">
            <input v-model="draftFor(set.id).headline" class="input" dir="auto" maxlength="120" required :aria-label="t('ads.headline')" :placeholder="t('ads.headline')" />
            <textarea v-model="draftFor(set.id).body" class="input min-h-16" dir="auto" maxlength="400" :aria-label="t('ads.body')" :placeholder="t('ads.body')" />
            <div class="grid grid-cols-2 gap-2">
              <input v-model="draftFor(set.id).cta" class="input" dir="auto" maxlength="40" :aria-label="t('ads.cta')" :placeholder="t('ads.cta')" />
              <input v-model="draftFor(set.id).link_url" class="input" type="url" dir="ltr" pattern="https://.*" :aria-label="t('ads.link')" :placeholder="t('ads.link')" />
            </div>
            <button type="submit" class="btn-primary text-sm" :disabled="busy">{{ t("ads.addCreative") }}</button>
          </form>
        </section>

        <form class="card space-y-2 p-4" @submit.prevent="addAdSet">
          <h2 class="font-semibold">{{ t("ads.newAdSet") }}</h2>
          <input v-model="newSet.name" class="input" dir="auto" maxlength="160" required :aria-label="t('ads.adSetName')" :placeholder="t('ads.adSetName')" />
          <div class="grid grid-cols-3 gap-2">
            <select v-model="newSet.placement" class="input" :aria-label="t('ads.placement')">
              <option value="feed">{{ t("ads.placements.feed") }}</option>
              <option value="marketplace">{{ t("ads.placements.marketplace") }}</option>
              <option value="search">{{ t("ads.placements.search") }}</option>
            </select>
            <input v-model="newSet.cpc" class="input" type="number" min="0" step="0.01" dir="ltr" aria-label="CPC" placeholder="CPC" />
            <input v-model="newSet.cpm" class="input" type="number" min="0" step="0.01" dir="ltr" aria-label="CPM" placeholder="CPM" />
          </div>
          <button type="submit" class="btn-primary text-sm" :disabled="busy">{{ t("ads.addAdSet") }}</button>
        </form>
      </template>
    </div>
  </AppShell>
</template>
