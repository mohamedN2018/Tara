<script setup lang="ts">
import { AlertTriangle, Pencil } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import AdImagePicker from "@/components/ads/AdImagePicker.vue";
import AdThumb from "@/components/ads/AdThumb.vue";
import AppShell from "@/components/layout/AppShell.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { scheduleLabel } from "@/lib/adSchedule";
import {
  adErrorKey,
  type AdSet,
  adsService,
  type Campaign,
  type CampaignReport,
  type Creative,
  type CreativePayload,
  SERVED_PLACEMENTS,
} from "@/services/ads";
import { useToastStore } from "@/stores/toasts";

const { t, locale } = useI18n();
const route = useRoute();
const toasts = useToastStore();
const id = computed(() => route.params.id as string);

const campaign = ref<Campaign | null>(null);
const report = ref<CampaignReport | null>(null);
const adSets = ref<AdSet[]>([]);
const loading = ref(true);
const error = ref(false);
const busy = ref(false);
const uploading = ref(false);

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
const schedule = computed(() => (campaign.value ? scheduleLabel(campaign.value, locale.value, t) : ""));

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

const newSet = ref({ name: "", placement: "feed", cpc: "0.10", cpm: "1.00", frequency_cap: 0 });
async function addAdSet() {
  if (busy.value) return;
  busy.value = true;
  try {
    await adsService.createAdSet(id.value, {
      ...newSet.value,
      name: newSet.value.name.trim(),
      frequency_cap: Math.max(0, Math.floor(Number(newSet.value.frequency_cap) || 0)),
    });
    newSet.value.name = "";
    adSets.value = await adsService.adSets(id.value);
  } catch (e) {
    toasts.push({ text: t(adErrorKey(e)), icon: "error" });
  } finally {
    busy.value = false;
  }
}

const blank = (): CreativePayload => ({ headline: "", body: "", cta: t("ads.defaultCta"), link_url: "", media_id: null });
const drafts = ref<Record<string, CreativePayload>>({});
function draftFor(adSetId: string) {
  drafts.value[adSetId] ??= blank();
  return drafts.value[adSetId];
}
async function addCreative(adSetId: string) {
  if (busy.value || uploading.value) return;
  busy.value = true;
  try {
    const draft = draftFor(adSetId);
    await adsService.createCreative(adSetId, { ...draft, media_id: draft.media_id || undefined });
    delete drafts.value[adSetId];
    adSets.value = await adsService.adSets(id.value);
    report.value = await adsService.report(id.value);
  } catch (e) {
    toasts.push({ text: t(adErrorKey(e)), icon: "error" });
  } finally {
    busy.value = false;
  }
}

// Edit and resubmit: a pending or rejected ad goes back to review.
const editingId = ref("");
const edit = ref<CreativePayload>(blank());
function startEdit(c: Creative) {
  editingId.value = c.id;
  edit.value = { headline: c.headline, body: c.body, cta: c.cta, link_url: c.link_url, media_id: c.media_id ?? null };
}
async function saveEdit() {
  if (!editingId.value || busy.value || uploading.value) return;
  busy.value = true;
  try {
    await adsService.updateCreative(editingId.value, edit.value);
    editingId.value = "";
    adSets.value = await adsService.adSets(id.value);
    toasts.success(t("commerce.ads.resubmitted"));
  } catch (e) {
    toasts.push({ text: t(adErrorKey(e)), icon: "error" });
  } finally {
    busy.value = false;
  }
}

const REVIEW_TONES: Record<string, string> = {
  approved: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
  rejected: "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300",
  pending: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
};

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
          <p class="mt-1 text-sm text-gray-600 dark:text-gray-300" data-testid="campaign-meta">
            {{ t("commerce.ads.objective") }}: <span class="font-medium">{{ t(`commerce.ads.objectives.${campaign.objective}`, campaign.objective) }}</span>
            <template v-if="schedule"> · {{ schedule }}</template>
          </p>
          <dl v-if="report" class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="campaign-stats">
            <div><dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("ads.spent") }}</dt><dd class="font-semibold" dir="ltr">{{ report.spent }} / {{ report.budget }}</dd></div>
            <div><dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("ads.impressions") }}</dt><dd class="font-semibold">{{ report.impressions }}</dd></div>
            <div><dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("ads.clicks") }}</dt><dd class="font-semibold">{{ report.clicks }}</dd></div>
            <div><dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("ads.ctr") }}</dt><dd class="font-semibold" dir="ltr">{{ (report.ctr * 100).toFixed(1) }}%</dd></div>
          </dl>
        </section>

        <section v-for="set in adSets" :key="set.id" class="card p-4" data-testid="ad-set">
          <h2 class="font-semibold" dir="auto">{{ set.name || t("ads.adSet") }}</h2>
          <p class="text-xs text-gray-500 dark:text-gray-400">
            {{ t(`ads.placements.${set.placement}`) }} · <span dir="ltr">CPC {{ set.cpc }} · CPM {{ set.cpm }}</span> ·
            {{ set.frequency_cap ? t("commerce.ads.capShort", { n: set.frequency_cap }) : t("commerce.ads.capDefault") }}
          </p>
          <ul class="mt-3 space-y-2">
            <li v-for="c in set.creatives" :key="c.id" class="rounded-lg border border-gray-100 p-3 text-sm dark:border-gray-800" data-testid="creative">
              <div class="flex items-start gap-3">
                <AdThumb v-if="c.media_id" :media-id="c.media_id" class="w-20 shrink-0" />
                <div class="min-w-0 flex-1">
                  <span class="flex items-center justify-between gap-2">
                    <span class="min-w-0 truncate font-medium" dir="auto">{{ c.headline }}</span>
                    <span class="shrink-0 rounded-full px-2 py-0.5 text-xs" :class="REVIEW_TONES[c.review_status] ?? ''" data-testid="creative-review">
                      {{ t(`ads.review.${c.review_status}`) }}
                    </span>
                  </span>
                  <span v-if="statsFor(c.id)" class="block text-xs text-gray-500 dark:text-gray-400">
                    {{ t("ads.impressions") }}: {{ statsFor(c.id)?.impressions }} · {{ t("ads.clicks") }}: {{ statsFor(c.id)?.clicks }}
                  </span>
                </div>
              </div>
              <div
                v-if="c.review_status === 'rejected'"
                class="mt-2 flex gap-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-800 dark:bg-red-950/40 dark:text-red-200"
                data-testid="creative-rejection"
              >
                <AlertTriangle class="h-4 w-4 shrink-0" aria-hidden="true" />
                <p class="min-w-0">
                  <span class="font-semibold">{{ t("commerce.ads.rejectedReason") }}</span>
                  <span dir="auto"> {{ c.review_notes || t("commerce.ads.noReason") }}</span>
                </p>
              </div>
              <button
                v-if="(c.review_status === 'rejected' || c.review_status === 'pending') && editingId !== c.id"
                type="button"
                class="btn-ghost mt-2 text-xs"
                data-testid="creative-edit"
                @click="startEdit(c)"
              >
                <Pencil class="h-3.5 w-3.5" aria-hidden="true" />
                {{ c.review_status === "rejected" ? t("commerce.ads.editResubmit") : t("commerce.ads.edit") }}
              </button>
              <form v-if="editingId === c.id" class="mt-3 space-y-2" data-testid="creative-edit-form" @submit.prevent="saveEdit">
                <AdImagePicker v-model="edit.media_id" :input-id="`edit-image-${c.id}`" :disabled="busy" @update:busy="uploading = $event" />
                <input v-model="edit.headline" class="input" dir="auto" maxlength="120" required :aria-label="t('ads.headline')" :placeholder="t('ads.headline')" />
                <textarea v-model="edit.body" class="input min-h-16" dir="auto" maxlength="400" :aria-label="t('ads.body')" :placeholder="t('ads.body')" />
                <div class="grid grid-cols-2 gap-2">
                  <input v-model="edit.cta" class="input" dir="auto" maxlength="40" :aria-label="t('ads.cta')" :placeholder="t('ads.cta')" />
                  <input v-model="edit.link_url" class="input" type="url" dir="ltr" pattern="https://.*" :aria-label="t('ads.link')" :placeholder="t('ads.link')" />
                </div>
                <div class="flex justify-end gap-2">
                  <button type="button" class="btn-ghost text-sm" @click="editingId = ''">{{ t("feed.cancel") }}</button>
                  <button type="submit" class="btn-primary text-sm" :disabled="busy || uploading">{{ t("commerce.ads.resubmit") }}</button>
                </div>
              </form>
            </li>
          </ul>
          <form class="mt-3 space-y-2 border-t border-gray-100 pt-3 dark:border-gray-800" data-testid="creative-form" @submit.prevent="addCreative(set.id)">
            <AdImagePicker v-model="draftFor(set.id).media_id" :input-id="`new-image-${set.id}`" :disabled="busy" @update:busy="uploading = $event" />
            <input v-model="draftFor(set.id).headline" class="input" dir="auto" maxlength="120" required :aria-label="t('ads.headline')" :placeholder="t('ads.headline')" />
            <textarea v-model="draftFor(set.id).body" class="input min-h-16" dir="auto" maxlength="400" :aria-label="t('ads.body')" :placeholder="t('ads.body')" />
            <div class="grid grid-cols-2 gap-2">
              <input v-model="draftFor(set.id).cta" class="input" dir="auto" maxlength="40" :aria-label="t('ads.cta')" :placeholder="t('ads.cta')" />
              <input v-model="draftFor(set.id).link_url" class="input" type="url" dir="ltr" pattern="https://.*" :aria-label="t('ads.link')" :placeholder="t('ads.link')" />
            </div>
            <button type="submit" class="btn-primary text-sm" :disabled="busy || uploading">{{ t("ads.addCreative") }}</button>
          </form>
        </section>

        <form class="card space-y-3 p-4" data-testid="ad-set-form" @submit.prevent="addAdSet">
          <h2 class="font-semibold">{{ t("ads.newAdSet") }}</h2>
          <input v-model="newSet.name" class="input" dir="auto" maxlength="160" required :aria-label="t('ads.adSetName')" :placeholder="t('ads.adSetName')" />
          <div class="grid gap-2 sm:grid-cols-2">
            <div>
              <label for="set-placement" class="mb-1 block text-xs font-medium">{{ t("ads.placement") }}</label>
              <select id="set-placement" v-model="newSet.placement" class="input">
                <option v-for="p in SERVED_PLACEMENTS" :key="p" :value="p">{{ t(`ads.placements.${p}`) }}</option>
              </select>
            </div>
            <div>
              <label for="set-cap" class="mb-1 block text-xs font-medium">{{ t("commerce.ads.frequencyCap") }}</label>
              <input id="set-cap" v-model.number="newSet.frequency_cap" class="input" type="number" min="0" step="1" dir="ltr" aria-describedby="set-cap-hint" />
            </div>
            <div>
              <label for="set-cpc" class="mb-1 block text-xs font-medium">{{ t("commerce.ads.cpc") }}</label>
              <input id="set-cpc" v-model="newSet.cpc" class="input" type="number" min="0" step="0.01" dir="ltr" />
            </div>
            <div>
              <label for="set-cpm" class="mb-1 block text-xs font-medium">{{ t("commerce.ads.cpm") }}</label>
              <input id="set-cpm" v-model="newSet.cpm" class="input" type="number" min="0" step="0.01" dir="ltr" />
            </div>
          </div>
          <p id="set-cap-hint" class="text-xs text-gray-500 dark:text-gray-400">{{ t("commerce.ads.frequencyHint") }}</p>
          <button type="submit" class="btn-primary text-sm" :disabled="busy">{{ t("ads.addAdSet") }}</button>
        </form>
      </template>
    </div>
  </AppShell>
</template>
