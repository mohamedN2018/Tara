<script setup lang="ts">
// A marketplace thread's picture in the inbox: the listing's cover (the
// thread's own snapshot of it), with the other person's face in the corner, so
// threads about different listings with the same person can be told apart.
import { Store } from "lucide-vue-next";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { useMediaUrl } from "@/lib/useMediaUrl";

const props = withDefaults(defineProps<{ coverMediaId?: string | null; name: string; peerMediaId?: string | null; size?: number }>(), {
  coverMediaId: null,
  peerMediaId: null,
  size: 48,
});
const cover = useMediaUrl(() => props.coverMediaId);
</script>

<template>
  <span class="relative block shrink-0" :style="{ width: `${size}px`, height: `${size}px` }" data-testid="listing-avatar">
    <span class="block h-full w-full overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-800">
      <img v-if="cover" :src="cover" class="h-full w-full object-cover" alt="" loading="lazy" data-testid="listing-avatar-cover" />
      <span v-else class="flex h-full w-full items-center justify-center bg-gradient-to-br from-accent-100 to-brand-100 text-accent-700 dark:from-accent-900/40 dark:to-brand-900/40 dark:text-accent-300">
        <Store class="h-5 w-5" aria-hidden="true" />
      </span>
    </span>
    <UserAvatar
      class="absolute -bottom-1 -end-1 ring-2 ring-white dark:ring-gray-900"
      :name="name"
      :media-id="peerMediaId"
      :size="Math.round(size * 0.45)"
    />
  </span>
</template>
