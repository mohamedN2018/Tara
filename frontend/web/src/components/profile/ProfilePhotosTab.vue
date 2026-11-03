<script setup lang="ts">
import { toRefs } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/states/EmptyState.vue";
import type { ProfileState } from "@/lib/useProfile";

const props = defineProps<{ state: ProfileState }>();
defineEmits<{ "open-photo": [src: string] }>();

const { photoUrls, displayName } = toRefs(props.state);
const { t } = useI18n();
</script>

<template>
  <div class="card p-4">
    <h2 class="mb-3 text-base font-bold">{{ t("profile.photos") }}</h2>
    <EmptyState v-if="photoUrls.length === 0">{{ t("profile.noPhotos") }}</EmptyState>
    <div v-else class="grid grid-cols-3 gap-1.5 sm:grid-cols-4">
      <button
        v-for="(src, i) in photoUrls"
        :key="i"
        class="aspect-square overflow-hidden rounded-lg bg-gray-100 transition hover:opacity-90 dark:bg-gray-800"
        @click="$emit('open-photo', src)"
      >
        <img :src="src" class="h-full w-full object-cover" loading="lazy" :alt="t('profile.photoAlt', { n: i + 1, name: displayName })" />
      </button>
    </div>
  </div>
</template>
