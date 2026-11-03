<script setup lang="ts">
// Square cover for one listing; falls back to the category gradient and icon.
import { computed } from "vue";

import { categoryGradient, categoryIcon } from "@/lib/listing";
import { useMediaUrl } from "@/lib/useMediaUrl";
import type { Listing } from "@/types";

const props = defineProps<{ listing: Listing }>();
const cover = useMediaUrl(() => props.listing.media?.[0]?.media_id);
const gradient = computed(() => categoryGradient(props.listing.category?.slug));
const icon = computed(() => categoryIcon(props.listing.category?.slug));
</script>

<template>
  <div class="aspect-square overflow-hidden rounded-xl bg-gray-100 dark:bg-gray-800">
    <img v-if="cover" :src="cover" class="h-full w-full object-cover" alt="" loading="lazy" />
    <div v-else class="flex h-full items-center justify-center bg-gradient-to-br text-gray-500 dark:text-gray-300" :class="gradient">
      <component :is="icon" class="h-8 w-8 opacity-70" aria-hidden="true" />
    </div>
  </div>
</template>
