<script setup lang="ts">
// An ad's image, small (advertiser's list, review queue).
import { useI18n } from "vue-i18n";

import { useMediaUrl } from "@/lib/useMediaUrl";

const props = defineProps<{ mediaId: string }>();
const { t } = useI18n();
const url = useMediaUrl(() => props.mediaId);
</script>

<template>
  <div class="aspect-[1.91/1] overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-800">
    <img v-if="url" :src="url" class="h-full w-full object-cover" :alt="t('commerce.ads.imageAlt')" loading="lazy" />
  </div>
</template>
