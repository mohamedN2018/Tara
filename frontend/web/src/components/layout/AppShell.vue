<script setup lang="ts">
import { onMounted } from "vue";

import { useNotificationStore } from "@/stores/notifications";
import { useUiStore } from "@/stores/ui";

import MobileNavigation from "./MobileNavigation.vue";
import SidebarNav from "./SidebarNav.vue";
import TopHeader from "./TopHeader.vue";

const ui = useUiStore();
const notifications = useNotificationStore();

onMounted(() => {
  notifications.bind();
  notifications.refresh();
});
</script>

<template>
  <div class="min-h-screen lg:grid lg:grid-cols-[260px_1fr]">
    <!-- Desktop sidebar -->
    <aside class="sticky top-0 hidden h-screen border-e border-gray-200 dark:border-gray-800 lg:block">
      <SidebarNav />
    </aside>

    <!-- Mobile drawer -->
    <Transition name="fade">
      <div
        v-if="ui.sidebarOpen"
        class="fixed inset-0 z-40 bg-black/40 lg:hidden"
        @click="ui.sidebarOpen = false"
      >
        <aside
          class="h-full w-64 bg-white shadow-xl dark:bg-gray-950"
          @click.stop
        >
          <SidebarNav />
        </aside>
      </div>
    </Transition>

    <div class="flex min-h-screen flex-col">
      <TopHeader />
      <main class="mx-auto w-full max-w-2xl flex-1 px-3 pb-24 pt-4 lg:pb-8">
        <slot />
      </main>
    </div>

    <MobileNavigation />
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
