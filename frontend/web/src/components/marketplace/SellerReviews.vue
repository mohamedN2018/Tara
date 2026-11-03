<script setup lang="ts">
// Buyer reviews of a seller, plus the review form for an eligible buyer
// (one who messaged the seller about this listing, once per listing).
import { Flag } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { apiError, httpStatus } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import { marketplaceService, type SellerReview } from "@/services/marketplace";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

import StarRating from "./StarRating.vue";

const props = defineProps<{ sellerId: string; listingId: string; canReview: boolean }>();
const emit = defineEmits<{ reviewed: [] }>();
const { t } = useI18n();
const directory = useDirectoryStore();
const toasts = useToastStore();

const reviews = ref<SellerReview[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(true);
const failed = ref(false);

const rating = ref<number | null>(null);
const body = ref("");
const submitting = ref(false);
const reportingId = ref<string | null>(null);
const reportReason = ref("");
// The server refused this buyer's review (too soon, or one already this month).
const refused = ref(false);
const REVIEW_ERRORS = {
  review_not_eligible_yet: "market.reviews.tooSoon",
  review_rate_limited: "market.reviews.tooOften",
};

async function load(more = false) {
  if (!more) loading.value = true;
  failed.value = false;
  try {
    const page = await marketplaceService.sellerReviews(props.sellerId, more ? (cursor.value ?? undefined) : undefined);
    reviews.value = more ? [...reviews.value, ...page.data] : page.data;
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch (e) {
    // 404: a seller with nothing public (blocked, unknown): no reviews to show.
    if (httpStatus(e) === 404) {
      reviews.value = [];
      hasMore.value = false;
    } else failed.value = true;
  } finally {
    loading.value = false;
  }
}
onMounted(() => load());
watch(() => props.sellerId, () => load());

async function submit() {
  if (!rating.value || submitting.value) return;
  submitting.value = true;
  try {
    const review = await marketplaceService.createReview(props.listingId, rating.value, body.value.trim());
    reviews.value = [review, ...reviews.value];
    rating.value = null;
    body.value = "";
    toasts.success(t("market.reviews.thanks"));
    emit("reviewed");
  } catch (e) {
    toasts.error(e, REVIEW_ERRORS);
    if (apiError(e).code in REVIEW_ERRORS) refused.value = true;
  } finally {
    submitting.value = false;
  }
}

async function sendReport(id: string) {
  if (!reportReason.value.trim()) return;
  try {
    await marketplaceService.reportReview(id, reportReason.value.trim());
    toasts.success(t("market.reportSent"));
    reportingId.value = null;
    reportReason.value = "";
  } catch (e) {
    toasts.error(e);
  }
}
</script>

<template>
  <section class="mt-6" aria-labelledby="seller-reviews-title">
    <h2 id="seller-reviews-title" class="section-title mb-3">{{ t("market.reviews.title") }}</h2>

    <form
      v-if="canReview && !refused"
      class="mb-4 space-y-2 rounded-xl border border-brand-100 bg-brand-50/50 p-3 dark:border-brand-900/60 dark:bg-brand-950/30"
      @submit.prevent="submit"
    >
      <p class="text-sm font-semibold">{{ t("market.reviews.write") }}</p>
      <StarRating :value="rating" editable @update:value="rating = $event" />
      <label for="review-body" class="sr-only">{{ t("market.reviews.body") }}</label>
      <textarea
        id="review-body"
        v-model="body"
        class="input min-h-20"
        dir="auto"
        rows="3"
        maxlength="2000"
        :placeholder="t('market.reviews.body')"
      />
      <div class="flex justify-end">
        <button type="submit" class="btn-primary" :disabled="!rating || submitting">
          {{ t("market.reviews.submit") }}
        </button>
      </div>
    </form>

    <div v-if="loading" class="space-y-2" aria-busy="true">
      <div v-for="i in 2" :key="i" class="skeleton h-16" />
    </div>
    <p v-else-if="failed" class="text-sm text-gray-500 dark:text-gray-400">
      {{ t("states.error") }}
      <button type="button" class="ms-1 font-semibold text-brand-600 dark:text-brand-300" @click="load()">
        {{ t("states.retry") }}
      </button>
    </p>
    <p v-else-if="!reviews.length" class="text-sm text-gray-500 dark:text-gray-400">{{ t("market.reviews.none") }}</p>

    <ul v-else class="space-y-3">
      <li v-for="r in reviews" :key="r.id" class="rounded-xl border border-gray-100 p-3 dark:border-gray-800">
        <div class="flex items-center gap-2">
          <UserAvatar :name="directory.label(r.buyer_id)" :media-id="directory.avatarOf(r.buyer_id)" :size="28" />
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-semibold" dir="auto">{{ directory.label(r.buyer_id) }}</p>
            <p class="text-[11px] text-gray-500 dark:text-gray-400">
              {{ relativeTime(r.created_at) }}
              <template v-if="r.listing_title"> · <span dir="auto">{{ r.listing_title }}</span></template>
            </p>
          </div>
          <StarRating :value="r.rating" :size="14" />
        </div>
        <p v-if="r.body" class="mt-2 whitespace-pre-wrap text-sm leading-relaxed" dir="auto">{{ r.body }}</p>
        <button
          type="button"
          class="mt-2 inline-flex items-center gap-1 text-[11px] text-gray-500 hover:text-red-500 dark:text-gray-400"
          :aria-expanded="reportingId === r.id"
          @click="reportingId = reportingId === r.id ? null : r.id"
        >
          <Flag class="h-3 w-3" aria-hidden="true" /> {{ t("market.reviews.report") }}
        </button>
        <div v-if="reportingId === r.id" class="mt-2 flex gap-2">
          <input
            v-model="reportReason"
            class="input py-1.5"
            dir="auto"
            maxlength="200"
            :aria-label="t('market.reportReason')"
            :placeholder="t('market.reportReason')"
          />
          <button type="button" class="btn-outline px-3 py-1.5" :disabled="!reportReason.trim()" @click="sendReport(r.id)">
            {{ t("market.report") }}
          </button>
        </div>
      </li>
    </ul>
    <div v-if="hasMore" class="mt-3 flex justify-center">
      <button type="button" class="btn-ghost" @click="load(true)">{{ t("feed.loadMore") }}</button>
    </div>
  </section>
</template>
