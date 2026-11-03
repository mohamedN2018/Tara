<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { adsService, type ReviewItem } from "@/services/ads";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const toasts = useToastStore();
const items = ref<ReviewItem[]>([]);
const loading = ref(true);
const error = ref(false);
const acting = ref("");

async function load() {
  loading.value = true;
  error.value = false;
  try {
    items.value = await adsService.reviewQueue();
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

async function decide(item: ReviewItem, decision: "approved" | "rejected") {
  if (acting.value) return;
  acting.value = item.id;
  try {
    await adsService.review(item.id, decision);
    items.value = items.value.filter((i) => i.id !== item.id);
  } catch (e) {
    toasts.error(e);
  } finally {
    acting.value = "";
  }
}

onMounted(load);
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[720px] space-y-4">
      <h1 class="text-xl font-bold">{{ t("ads.reviewQueue") }}</h1>
      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error" @retry="load" />
      <EmptyState v-else-if="!items.length">{{ t("ads.reviewEmpty") }}</EmptyState>
      <ul v-else class="space-y-3">
        <li v-for="item in items" :key="item.id" class="card p-4" data-testid="review-item">
          <p class="text-xs text-gray-500" dir="auto">{{ item.advertiser_name }} · {{ item.campaign_name }} · {{ t(`ads.placements.${item.placement}`) }}</p>
          <h2 class="mt-1 font-semibold" dir="auto">{{ item.headline }}</h2>
          <p v-if="item.body" class="mt-1 whitespace-pre-wrap break-words text-sm" dir="auto">{{ item.body }}</p>
          <p class="mt-1 text-xs text-gray-500" dir="auto">{{ item.cta }}</p>
          <!-- Shown as text: a reviewer shouldn't have to open an unreviewed link. -->
          <p v-if="item.link_url" class="mt-1 break-all text-xs text-gray-500" dir="ltr">{{ item.link_url }}</p>
          <div class="mt-3 flex justify-end gap-2">
            <button class="btn-ghost text-sm" :disabled="acting === item.id" @click="decide(item, 'rejected')">{{ t("ads.reject") }}</button>
            <button class="btn-primary text-sm" :disabled="acting === item.id" @click="decide(item, 'approved')">{{ t("ads.approve") }}</button>
          </div>
        </li>
      </ul>
    </div>
  </AppShell>
</template>
