<script setup lang="ts">
import { MapPin } from "lucide-vue-next";
import { computed } from "vue";

import { useMediaUrl } from "@/lib/useMediaUrl";
import type { Listing } from "@/types";

const props = defineProps<{ listing: Listing & { cover_media_id?: string | null } }>();

const cover = useMediaUrl(() => props.listing.cover_media_id);
const price = computed(
  () => `${props.listing.price} ${props.listing.currency}`,
);
</script>

<template>
  <RouterLink :to="`/marketplace/${listing.id}`" class="card block overflow-hidden transition hover:shadow-md">
    <div class="aspect-square bg-gray-100 dark:bg-gray-800">
      <img v-if="cover" :src="cover" class="h-full w-full object-cover" loading="lazy" alt="" />
      <div v-else class="flex h-full items-center justify-center text-gray-400">—</div>
    </div>
    <div class="p-3">
      <p class="font-bold text-brand-600">{{ price }}</p>
      <h3 class="truncate text-sm font-medium">{{ listing.title }}</h3>
      <p class="mt-1 flex items-center gap-1 text-xs text-gray-500">
        <MapPin class="h-3 w-3" /> {{ listing.location || "—" }}
      </p>
    </div>
  </RouterLink>
</template>
