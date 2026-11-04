<script setup lang="ts">
// Seller summary on a listing: name, rating, member since, active listings and
// an activity hint. Loads its own data; a failure just hides the stats.
import { BadgeCheck, Clock, Package } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { marketplaceService, type SellerSummary } from "@/services/marketplace";
import { useDirectoryStore } from "@/stores/directory";

import StarRating from "./StarRating.vue";

// `shopLink=false` on the shop page itself (it is already there).
const props = withDefaults(defineProps<{ sellerId: string; shopLink?: boolean }>(), { shopLink: true });
const { t, locale } = useI18n();
const directory = useDirectoryStore();

const summary = ref<SellerSummary | null>(null);

async function load() {
  summary.value = null;
  try {
    summary.value = await marketplaceService.seller(props.sellerId);
  } catch {
    summary.value = null;
  }
}
onMounted(load);
watch(() => props.sellerId, load);

const since = computed(() => {
  if (!summary.value) return "";
  try {
    return new Intl.DateTimeFormat(locale.value, { month: "long", year: "numeric" }).format(
      new Date(summary.value.member_since),
    );
  } catch {
    return (summary.value.member_since ?? "").slice(0, 7);
  }
});
</script>

<template>
  <section class="mt-4 rounded-xl border border-gray-100 p-3 dark:border-gray-800" :aria-label="t('market.seller.title')">
    <RouterLink
      :to="shopLink ? { name: 'marketplace-seller', params: { id: sellerId } } : { name: 'profile-by-id', params: { id: sellerId } }"
      class="flex items-center gap-3 rounded-lg transition hover:opacity-90"
      data-testid="seller-link"
    >
      <UserAvatar :name="directory.label(sellerId)" :media-id="directory.avatarOf(sellerId)" :size="44" />
      <div class="min-w-0">
        <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("market.listedBy") }}</p>
        <p class="truncate text-sm font-semibold" dir="auto">{{ directory.label(sellerId) }}</p>
      </div>
      <span class="ms-auto text-xs font-medium text-brand-600 dark:text-brand-300">
        {{ shopLink ? t("market.viewSeller") : t("commerce.shop.viewProfile") }}
      </span>
    </RouterLink>

    <div v-if="summary" class="mt-3 grid grid-cols-1 gap-2 text-xs text-gray-600 dark:text-gray-300 sm:grid-cols-2">
      <p class="flex items-center gap-1.5">
        <template v-if="summary.rating_count">
          <StarRating :value="summary.rating_avg" :size="14" />
          <span class="font-semibold tabular-nums">{{ summary.rating_avg?.toFixed(1) }}</span>
          <span class="text-gray-500 dark:text-gray-400">({{ t("market.reviews.count", summary.rating_count) }})</span>
        </template>
        <span v-else class="text-gray-500 dark:text-gray-400">{{ t("market.reviews.none") }}</span>
      </p>
      <p class="flex items-center gap-1.5">
        <BadgeCheck class="h-4 w-4 shrink-0 text-brand-500" aria-hidden="true" />
        {{ t("market.seller.memberSince", { date: since }) }}
      </p>
      <p class="flex items-center gap-1.5">
        <Package class="h-4 w-4 shrink-0 text-brand-500" aria-hidden="true" />
        <RouterLink
          v-if="shopLink && summary.active_listings_count"
          :to="{ name: 'marketplace-seller', params: { id: sellerId } }"
          class="font-medium text-brand-600 hover:underline dark:text-brand-300"
        >
          {{ t("market.seller.activeListings", summary.active_listings_count) }}
        </RouterLink>
        <template v-else>{{ t("market.seller.activeListings", summary.active_listings_count) }}</template>
        <span v-if="summary.sold_listings_count" class="text-gray-500 dark:text-gray-400">
          · {{ t("market.seller.sold", summary.sold_listings_count) }}
        </span>
      </p>
      <p v-if="summary.response_hint" class="flex items-center gap-1.5">
        <Clock class="h-4 w-4 shrink-0 text-brand-500" aria-hidden="true" />
        {{ t(`market.seller.hints.${summary.response_hint}`) }}
      </p>
    </div>
  </section>
</template>
