<script setup lang="ts">
import { useMediaUrl } from "@/lib/useMediaUrl";

const props = defineProps<{ mediaId: string; postId: string; label: string }>();
const url = useMediaUrl(() => props.mediaId);
</script>

<template>
  <li class="aspect-square overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-800">
    <RouterLink :to="`/posts/${postId}`" class="block h-full w-full" :aria-label="label">
      <img v-if="url" :src="url" alt="" class="h-full w-full object-cover" loading="lazy" />
    </RouterLink>
  </li>
</template>
