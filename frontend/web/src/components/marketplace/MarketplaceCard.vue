<script setup lang="ts">
import { Bookmark, MapPin } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { categoryGradient, categoryIcon, formatPrice } from "@/lib/listing";
import { useMediaUrl } from "@/lib/useMediaUrl";
import { useDirectoryStore } from "@/stores/directory";
import type { Listing } from "@/types";

const props = defineProps<{ listing: Listing }>();
const { t } = useI18n();
const directory = useDirectoryStore();

const cover = useMediaUrl(() => props.listing.media?.[0]?.media_id);
const price = computed(() => formatPrice(props.listing.price, props.listing.currency));
const gradient = computed(() => categoryGradient(props.listing.category?.slug));
const icon = computed(() => categoryIcon(props.listing.category?.slug));
const conditionLabel = computed(() => t(`market.conditions.${props.listing.condition}`));
const inactive = computed(() => props.listing.status !== "active");
</script>

<template>
  <div class="card overflow-hidden transition hover:shadow-md">
    <RouterLink :to="`/marketplace/${listing.id}`" class="block">
      <div class="relative aspect-square">
        <img v-if="cover" :src="cover" class="h-full w-full object-cover" loading="lazy" :alt="listing.title" />
        <div
          v-else
          class="flex h-full flex-col items-center justify-center gap-2 bg-gradient-to-br text-gray-500 dark:text-gray-300"
          :class="gradient"
        >
          <component :is="icon" class="h-10 w-10 opacity-70" />
          <span v-if="listing.category" class="text-xs font-medium opacity-80">
            {{ listing.category.name }}
          </span>
        </div>

        <span
          class="absolute top-2 start-2 rounded-full bg-white/90 px-2 py-0.5 text-[11px] font-semibold text-gray-700 shadow-sm dark:bg-gray-900/80 dark:text-gray-200"
        >
          {{ conditionLabel }}
        </span>
        <span
          v-if="inactive"
          class="absolute top-2 end-2 rounded-full bg-gray-900/80 px-2 py-0.5 text-[11px] font-semibold text-white"
        >
          {{ t(`market.statuses.${listing.status}`) }}
        </span>
      </div>

      <div class="p-3">
        <p class="font-bold text-brand-600 dark:text-brand-300">{{ price }}</p>
        <h3 class="truncate text-sm font-medium" dir="auto">{{ listing.title }}</h3>
        <p class="mt-1 flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
          <MapPin class="h-3 w-3 shrink-0" />
          <span class="truncate" dir="auto">{{ listing.location || "—" }}</span>
        </p>
      </div>
    </RouterLink>

    <div class="flex items-center justify-between gap-2 px-3 pb-3">
      <RouterLink
        :to="{ name: 'profile-by-id', params: { id: listing.seller_id } }"
        class="flex min-w-0 items-center gap-1.5 text-xs text-gray-500 hover:text-brand-600 dark:text-gray-400"
        :title="t('market.viewSeller')"
      >
        <UserAvatar :name="directory.label(listing.seller_id)" :media-id="directory.avatarOf(listing.seller_id)" :size="20" />
        <span class="truncate" dir="auto">{{ directory.label(listing.seller_id) }}</span>
      </RouterLink>
      <span
        v-if="listing.save_count"
        class="inline-flex shrink-0 items-center gap-1 text-xs text-gray-500 dark:text-gray-400"
      >
        <Bookmark class="h-3 w-3" /> {{ listing.save_count }}
      </span>
    </div>
  </div>
</template>
