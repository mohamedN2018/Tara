<script setup lang="ts">
import { onMounted, onUnmounted } from "vue";

import OfflineState from "@/components/states/OfflineState.vue";
import { realtime } from "@/lib/ws";
import { useUiStore } from "@/stores/ui";

const ui = useUiStore();

let unsub: (() => void) | null = null;

function setOnline() {
  ui.online = navigator.onLine;
}

onMounted(() => {
  setOnline();
  window.addEventListener("online", setOnline);
  window.addEventListener("offline", setOnline);
  // Mirror the realtime socket state into the offline banner.
  unsub = realtime.on("_status", (f) => {
    if (f.status === "closed" && navigator.onLine === false) ui.online = false;
    if (f.status === "open") ui.online = true;
  });
});

onUnmounted(() => {
  window.removeEventListener("online", setOnline);
  window.removeEventListener("offline", setOnline);
  unsub?.();
});
</script>

<template>
  <OfflineState v-if="!ui.online" />
  <RouterView />
</template>
