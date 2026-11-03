<script setup lang="ts">
import { computed } from "vue";

import { initials } from "@/lib/format";
import { useMediaUrl } from "@/lib/useMediaUrl";

const props = withDefaults(
  defineProps<{ name: string; mediaId?: string | null; size?: number; ring?: boolean }>(),
  { mediaId: null, size: 40, ring: false },
);

// Initials sit on one of a few brand-family gradients, picked by name, so
// people stay recognisable without the UI turning into a rainbow.
const GRADIENTS = [
  "linear-gradient(135deg,#6A00F4,#A855F7)",
  "linear-gradient(135deg,#A855F7,#FF4ED8)",
  "linear-gradient(135deg,#3B2BD9,#6A00F4)",
  "linear-gradient(135deg,#FF4ED8,#FF8A65)",
  "linear-gradient(135deg,#5B21B6,#22D3EE)",
  "linear-gradient(135deg,#7C3AED,#F472B6)",
];

function pick(key: string): string {
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = key.charCodeAt(i) + ((hash << 5) - hash);
  return GRADIENTS[Math.abs(hash) % GRADIENTS.length];
}

const url = useMediaUrl(() => props.mediaId);
const style = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  backgroundImage: url.value ? undefined : pick(props.name),
  fontSize: `${Math.round(props.size / 2.6)}px`,
}));
</script>

<template>
  <span
    class="relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-gray-200 font-bold tracking-tight text-white dark:bg-gray-800"
    :class="ring ? 'ring-2 ring-white dark:ring-gray-900' : ''"
    :style="style"
  >
    <img v-if="url" :src="url" :alt="name" class="h-full w-full object-cover" loading="lazy" decoding="async" />
    <span v-else dir="auto">{{ initials(name) }}</span>
  </span>
</template>
