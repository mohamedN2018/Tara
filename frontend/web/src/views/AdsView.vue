<script setup lang="ts">
import { Megaphone, Plus } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { adErrorKey, adsService, CAMPAIGN_CURRENCIES, type Campaign } from "@/services/ads";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();
const router = useRouter();
const auth = useAuthStore();

const campaigns = ref<Campaign[]>([]);
const loading = ref(true);
const error = ref(false);
const creating = ref(false);
const saving = ref(false);
const formError = ref("");
const form = ref({ name: "", budget: "", currency: "USD" });

const isReviewer = computed(() => auth.can("ads.review"));

async function load() {
  loading.value = true;
  error.value = false;
  try {
    campaigns.value = await adsService.campaigns();
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

async function create() {
  if (saving.value) return;
  saving.value = true;
  formError.value = "";
  try {
    const campaign = await adsService.createCampaign({ ...form.value, name: form.value.name.trim() });
    router.push({ name: "ad-campaign", params: { id: campaign.id } });
  } catch (e) {
    formError.value = t(adErrorKey(e));
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[720px] space-y-4">
      <div class="flex items-center justify-between gap-2">
        <h1 class="text-xl font-bold">{{ t("ads.title") }}</h1>
        <div class="flex gap-2">
          <RouterLink v-if="isReviewer" to="/ads/review" class="btn-ghost text-sm">{{ t("ads.reviewQueue") }}</RouterLink>
          <button class="btn-primary" @click="creating = !creating"><Plus class="h-4 w-4" /> {{ t("ads.newCampaign") }}</button>
        </div>
      </div>

      <form v-if="creating" class="card space-y-3 p-4" @submit.prevent="create">
        <div>
          <label for="campaign-name" class="mb-1 block text-sm font-medium">{{ t("ads.campaignName") }}</label>
          <input id="campaign-name" v-model="form.name" class="input" dir="auto" maxlength="160" required />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label for="campaign-budget" class="mb-1 block text-sm font-medium">{{ t("ads.budget") }}</label>
            <input id="campaign-budget" v-model="form.budget" class="input" type="number" min="0" step="0.01" dir="ltr" required />
          </div>
          <div>
            <label for="campaign-currency" class="mb-1 block text-sm font-medium">{{ t("market.currency") }}</label>
            <select id="campaign-currency" v-model="form.currency" class="input" dir="ltr" required>
              <option v-for="c in CAMPAIGN_CURRENCIES" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>
        </div>
        <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("ads.noBilling") }}</p>
        <p v-if="formError" class="text-sm text-red-500" role="alert">{{ formError }}</p>
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="creating = false">{{ t("feed.cancel") }}</button>
          <button type="submit" class="btn-primary" :disabled="saving">{{ t("ads.createCampaign") }}</button>
        </div>
      </form>

      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error" @retry="load" />
      <EmptyState v-else-if="!campaigns.length">{{ t("ads.noCampaigns") }}</EmptyState>
      <ul v-else class="space-y-2">
        <li v-for="c in campaigns" :key="c.id">
          <RouterLink :to="{ name: 'ad-campaign', params: { id: c.id } }" class="card flex items-center gap-3 p-4 transition hover:shadow-sm">
            <Megaphone class="h-5 w-5 shrink-0 text-brand-600 dark:text-brand-300" />
            <span class="min-w-0 flex-1">
              <span class="block truncate font-medium" dir="auto">{{ c.name }}</span>
              <span class="block text-xs text-gray-500 dark:text-gray-400" dir="ltr">{{ c.spent }} / {{ c.budget }} {{ c.currency }}</span>
            </span>
            <span class="rounded-full bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-800">{{ t(`ads.status.${c.status}`) }}</span>
          </RouterLink>
        </li>
      </ul>
    </div>
  </AppShell>
</template>
