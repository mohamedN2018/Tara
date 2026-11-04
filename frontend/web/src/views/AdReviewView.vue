<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AdThumb from "@/components/ads/AdThumb.vue";
import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { adErrorKey, adsService, type ReviewItem } from "@/services/ads";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const toasts = useToastStore();
const items = ref<ReviewItem[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
const acting = ref("");
// The item whose rejection reason is being written: the advertiser reads it.
const rejecting = ref("");
const notes = ref("");

async function load(more = false) {
  if (more) loadingMore.value = true;
  else loading.value = true;
  error.value = false;
  try {
    const page = await adsService.reviewQueue(more ? cursor.value : null);
    items.value = more ? [...items.value, ...page.data] : page.data;
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch (e) {
    if (more) toasts.error(e);
    else error.value = true;
  } finally {
    loading.value = false;
    loadingMore.value = false;
  }
}

function startReject(item: ReviewItem) {
  rejecting.value = item.id;
  notes.value = "";
}

async function decide(item: ReviewItem, decision: "approved" | "rejected") {
  if (acting.value) return;
  if (decision === "rejected" && !notes.value.trim()) return;
  acting.value = item.id;
  try {
    await adsService.review(item.id, decision, decision === "rejected" ? notes.value.trim() : "");
    items.value = items.value.filter((i) => i.id !== item.id);
    rejecting.value = "";
  } catch (e) {
    toasts.push({ text: t(adErrorKey(e)), icon: "error" });
  } finally {
    acting.value = "";
  }
}

onMounted(() => load());
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[720px] space-y-4">
      <h1 class="text-xl font-bold">{{ t("ads.reviewQueue") }}</h1>
      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error" @retry="load()" />
      <EmptyState v-else-if="!items.length">{{ t("ads.reviewEmpty") }}</EmptyState>
      <ul v-else class="space-y-3">
        <li v-for="item in items" :key="item.id" class="card p-4" data-testid="review-item">
          <p class="text-xs text-gray-500 dark:text-gray-400" dir="auto">{{ item.advertiser_name }} · {{ item.campaign_name }} · {{ t(`ads.placements.${item.placement}`) }}</p>
          <h2 class="mt-1 font-semibold" dir="auto">{{ item.headline }}</h2>
          <p v-if="item.body" class="mt-1 whitespace-pre-wrap break-words text-sm" dir="auto">{{ item.body }}</p>
          <AdThumb v-if="item.media_id" :media-id="item.media_id" class="mt-2 max-w-sm" />
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400" dir="auto">{{ item.cta }}</p>
          <!-- Shown as text: a reviewer shouldn't have to open an unreviewed link. -->
          <p v-if="item.link_url" class="mt-1 break-all text-xs text-gray-500 dark:text-gray-400" dir="ltr">{{ item.link_url }}</p>
          <form v-if="rejecting === item.id" class="mt-3 space-y-2" @submit.prevent="decide(item, 'rejected')">
            <label :for="`reject-${item.id}`" class="block text-sm font-medium">{{ t("commerce.ads.rejectReason") }}</label>
            <textarea
              :id="`reject-${item.id}`"
              v-model="notes"
              class="input min-h-16"
              dir="auto"
              maxlength="2000"
              required
              :aria-describedby="`reject-hint-${item.id}`"
            />
            <p :id="`reject-hint-${item.id}`" class="text-xs text-gray-500 dark:text-gray-400">{{ t("commerce.ads.rejectHint") }}</p>
            <div class="flex justify-end gap-2">
              <button type="button" class="btn-ghost text-sm" @click="rejecting = ''">{{ t("feed.cancel") }}</button>
              <button type="submit" class="btn-primary text-sm" :disabled="acting === item.id || !notes.trim()" data-testid="confirm-reject">
                {{ t("ads.reject") }}
              </button>
            </div>
          </form>
          <div v-else class="mt-3 flex justify-end gap-2">
            <button class="btn-ghost text-sm" :disabled="acting === item.id" @click="startReject(item)">{{ t("ads.reject") }}</button>
            <button class="btn-primary text-sm" :disabled="acting === item.id" @click="decide(item, 'approved')">{{ t("ads.approve") }}</button>
          </div>
        </li>
      </ul>
      <div v-if="hasMore" class="flex justify-center">
        <button class="btn-ghost" :disabled="loadingMore" @click="load(true)">
          {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
        </button>
      </div>
    </div>
  </AppShell>
</template>
