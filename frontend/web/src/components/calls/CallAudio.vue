<script setup lang="ts">
// Plays one remote audio track. Everyone is heard, also people whose tile does
// not fit the nine-tile grid. LiveKit routes these elements to the chosen speaker.
import type { Track } from "livekit-client";
import { onBeforeUnmount, onMounted, ref } from "vue";

const props = defineProps<{ track: Track }>();
const el = ref<HTMLAudioElement | null>(null);

onMounted(() => {
  if (el.value) props.track.attach(el.value);
});
onBeforeUnmount(() => {
  if (el.value) props.track.detach(el.value);
});
</script>

<template>
  <audio ref="el" autoplay class="hidden" />
</template>
