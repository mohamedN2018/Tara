<script setup lang="ts">
// Marketplace chats are about one listing: show it under the chat header with
// its price and a link to it. A listing the viewer can no longer see (sold and
// hidden, removed) answers 404 and the strip says so.
import { Store } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ListingThumb from "@/components/marketplace/ListingThumb.vue";
import PriceTag from "@/components/marketplace/PriceTag.vue";
import { marketplaceService } from "@/services/marketplace";
import type { Listing } from "@/types";

const props = defineProps<{ listingId: string }>();
const { t } = useI18n();
const listing = ref<Listing | null>(null);
const gone = ref(false);

async function load() {
  listing.value = null;
  gone.value = false;
  try {
    listing.value = await marketplaceService.get(props.listingId);
  } catch {
    gone.value = true;
  }
}
watch(() => props.listingId, load);
onMounted(load);
</script>

<template>
  <div class="flex items-center gap-3 border-b border-gray-200 bg-gray-50 px-3 py-2 dark:border-gray-800 dark:bg-gray-900/60" data-testid="listing-strip">
    <template v-if="listing">
      <span class="h-11 w-11 shrink-0 overflow-hidden rounded-lg"><ListingThumb :listing="listing" /></span>
      <span class="min-w-0 flex-1">
        <span class="block text-[11px] font-semibold uppercase tracking-wide text-accent-700 dark:text-accent-300">{{ t("messenger.listing.about") }}</span>
        <span class="block truncate text-sm font-semibold" dir="auto">{{ listing.title }}</span>
        <PriceTag :listing="listing" size="sm" />
      </span>
      <RouterLink :to="`/marketplace/${listing.id}`" class="btn-soft shrink-0 px-3 py-1.5 text-xs" data-testid="listing-strip-link">
        {{ t("messenger.listing.view") }}
      </RouterLink>
    </template>
    <p v-else-if="gone" class="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
      <Store class="h-4 w-4" aria-hidden="true" /> {{ t("messenger.listing.unavailable") }}
    </p>
    <p v-else class="text-xs text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
  </div>
</template>
