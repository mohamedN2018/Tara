<script setup lang="ts">
// The marketplace frame: the app shell without its own rails, the marketplace
// navigation column on the start side and the page on the rest. "Create new
// listing" opens the form here, so it works from every marketplace page.
import { defineAsyncComponent, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import { useToastStore } from "@/stores/toasts";
import type { Listing } from "@/types";

import type { MarketTab } from "./hubs";
import MarketplaceNav from "./MarketplaceNav.vue";
import { useCategories } from "./useCategories";

withDefaults(defineProps<{ active?: MarketTab | ""; category?: string; q?: string }>(), {
  active: "",
  category: "",
  q: "",
});
const emit = defineEmits<{ created: [listing: Listing] }>();

const CreateListingModal = defineAsyncComponent(() => import("./CreateListingModal.vue"));

const { t } = useI18n();
const router = useRouter();
const toasts = useToastStore();
const { categories, ready } = useCategories();
ready.catch(() => {}); // the column just shows no categories

const creating = ref(false);
defineExpose({ openCreate: () => (creating.value = true) });

function onCreated(listing: Listing) {
  creating.value = false;
  toasts.success(
    listing.status === "active"
      ? t("market.posted")
      : listing.status === "draft"
        ? t("commerce.listing.draftSaved")
        : t("market.pendingReview"),
  );
  emit("created", listing);
  // Surface it under Selling.
  router.push({ path: "/marketplace", query: { tab: "selling" } });
}
</script>

<template>
  <AppShell :left="false" :right="false">
    <div class="flex gap-5 xl:gap-6">
      <MarketplaceNav
        variant="rail"
        :active="active"
        :categories="categories"
        :category="category"
        :q="q"
        @create="creating = true"
      />
      <div class="min-w-0 flex-1">
        <MarketplaceNav variant="bar" :active="active" @create="creating = true" />
        <slot :categories="categories" />
      </div>
    </div>
    <CreateListingModal
      v-if="creating"
      :categories="categories"
      @close="creating = false"
      @created="onCreated"
    />
  </AppShell>
</template>
