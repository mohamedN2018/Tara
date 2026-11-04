<script setup lang="ts">
// A seller's shop inside the marketplace frame: summary, public listings and
// reviews. Reached from a listing's seller card and from listing cards.
import { computed } from "vue";
import { useRoute } from "vue-router";

import MarketplaceLayout from "@/components/marketplace/MarketplaceLayout.vue";
import SellerShop from "@/components/marketplace/SellerShop.vue";

const route = useRoute();
const sellerId = computed(() => route.params.id as string);
</script>

<template>
  <MarketplaceLayout>
    <SellerShop :seller-id="sellerId" />
  </MarketplaceLayout>
</template>
