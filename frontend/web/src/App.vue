<script setup lang="ts">
import { onMounted, onUnmounted, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import OfflineState from "@/components/states/OfflineState.vue";
import Toaster from "@/components/common/Toaster.vue";
import { realtime } from "@/lib/ws";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";
import { useUiStore } from "@/stores/ui";

const { t } = useI18n();
const route = useRoute();
const ui = useUiStore();
const auth = useAuthStore();
const directory = useDirectoryStore();
const toasts = useToastStore();

const unsubs: Array<() => void> = [];

function setOnline() {
  ui.online = navigator.onLine;
}

// Keep the directory seeded with the current user (so "You" resolves anywhere).
function seedSelf() {
  if (auth.account?.id && auth.profile) {
    directory.remember(
      auth.account.id,
      auth.profile.display_name,
      auth.profile.avatar_media_id,
      auth.profile.handle,
    );
  }
}

onMounted(() => {
  setOnline();
  window.addEventListener("online", setOnline);
  window.addEventListener("offline", setOnline);
  seedSelf();

  // Mirror the realtime socket state into the offline banner.
  unsubs.push(
    realtime.on("_status", (f) => {
      if (f.status === "closed" && navigator.onLine === false) ui.online = false;
      if (f.status === "open") ui.online = true;
    }),
  );

  // App-wide live toasts (real-time across every page).
  unsubs.push(
    realtime.on("notification.created", (f) => {
      // Messages already get their own toast below (one toast per message, not two).
      if (f.kind === "message") return;
      toasts.push({ text: t("toasts.newNotification"), icon: "bell", to: "/notifications" });
    }),
  );
  unsubs.push(
    realtime.on("chat.message.created", (f) => {
      // The gateway also echoes our own messages (one per recipient, sender included).
      if (f.sender === auth.account?.id || f.muted) return;
      const convoId = f.conversation_id as string | undefined;
      // Don't toast for the conversation the user is already reading.
      if (convoId && route.path === `/messages/${convoId}`) return;
      const preview = (f.preview as string) || t("toasts.newMessage");
      toasts.push({ text: preview, icon: "message", to: convoId ? `/messages/${convoId}` : "/messages" });
    }),
  );
});

watch(
  () => [auth.account?.id, auth.profile?.display_name],
  seedSelf,
);

onUnmounted(() => {
  window.removeEventListener("online", setOnline);
  window.removeEventListener("offline", setOnline);
  unsubs.forEach((u) => u());
});
</script>

<template>
  <OfflineState v-if="!ui.online" />
  <!-- Keep the feed alive so returning to Home is instant (preserves scroll
       position + already-loaded posts instead of refetching). -->
  <RouterView v-slot="{ Component }">
    <KeepAlive include="HomeView" :max="1">
      <component :is="Component" />
    </KeepAlive>
  </RouterView>
  <Toaster />
</template>
