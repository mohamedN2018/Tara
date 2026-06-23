<script setup lang="ts">
import { computed } from "vue";

import { avatarColor, initials } from "@/lib/format";
import { useMediaUrl } from "@/lib/useMediaUrl";

const props = withDefaults(
  defineProps<{ name: string; mediaId?: string | null; size?: number }>(),
  { mediaId: null, size: 40 },
);

const url = useMediaUrl(() => props.mediaId);
const style = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  backgroundColor: avatarColor(props.name),
  fontSize: `${Math.round(props.size / 2.5)}px`,
}));
</script>

<template>
  <span
    class="inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full font-semibold text-white"
    :style="style"
  >
    <img v-if="url" :src="url" :alt="name" class="h-full w-full object-cover" />
    <template v-else>{{ initials(name) }}</template>
  </span>
</template>
