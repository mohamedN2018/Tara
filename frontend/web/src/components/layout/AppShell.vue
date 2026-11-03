<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AppNavbar from "@/components/layout/AppNavbar.vue";
import LeftSidebar from "@/components/layout/LeftSidebar.vue";
import MobileBottomNavigation from "@/components/layout/MobileBottomNavigation.vue";
import RightSidebar from "@/components/layout/RightSidebar.vue";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { useNotificationStore } from "@/stores/notifications";
import { usePresenceStore } from "@/stores/presence";
import { useUiStore } from "@/stores/ui";

// `right=false` lets a view drop the right rail (e.g. full-width pages like chat).
withDefaults(defineProps<{ right?: boolean }>(), { right: true });

const { t } = useI18n();
const ui = useUiStore();
const drawer = ref<HTMLElement | null>(null);
useFocusTrap(drawer);
const notifications = useNotificationStore();
const presence = usePresenceStore();

onMounted(() => {
  notifications.bind();
  notifications.refresh();
  presence.bind();
});
</script>

<template>
  <div class="min-h-screen bg-gray-100 dark:bg-gray-950">
    <AppNavbar />

    <!-- Mobile left-sidebar drawer -->
    <Transition name="fade">
      <div
        v-if="ui.sidebarOpen"
        class="fixed inset-0 z-40 bg-black/40 lg:hidden"
        @click="ui.sidebarOpen = false"
      >
        <aside
          ref="drawer"
          role="dialog"
          aria-modal="true"
          :aria-label="t('nav.menu')"
          tabindex="-1"
          class="h-full w-72 overflow-y-auto bg-gray-50 pt-16 shadow-xl dark:bg-gray-900"
          @click.stop
        >
          <LeftSidebar />
        </aside>
      </div>
    </Transition>

    <!-- Full-width: side rails are pinned to the screen edges (no centered container). -->
    <div class="flex w-full gap-4 px-2 pt-16 sm:px-4 xl:px-6">
      <!-- Left rail (desktop) — fixed on the side -->
      <aside class="sticky top-16 hidden h-[calc(100vh-4rem)] w-64 shrink-0 overflow-y-auto lg:block xl:w-72">
        <LeftSidebar />
      </aside>

      <!-- Center -->
      <main class="min-w-0 flex-1 pb-24 pt-1 lg:pb-8">
        <slot />
      </main>

      <!-- Right rail (wide desktop) — fixed on the side -->
      <aside
        v-if="right"
        class="sticky top-16 hidden h-[calc(100vh-4rem)] w-72 shrink-0 overflow-y-auto xl:block 2xl:w-80"
      >
        <slot name="right"><RightSidebar /></slot>
      </aside>
    </div>

    <MobileBottomNavigation />
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
