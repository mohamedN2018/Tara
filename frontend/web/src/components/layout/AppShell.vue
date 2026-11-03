<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AppNavbar from "@/components/layout/AppNavbar.vue";
import LeftSidebar from "@/components/layout/LeftSidebar.vue";
import MobileBottomNavigation from "@/components/layout/MobileBottomNavigation.vue";
import RightSidebar from "@/components/layout/RightSidebar.vue";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { useAuthStore } from "@/stores/auth";
import { useChatUnreadStore } from "@/stores/chatUnread";
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
const auth = useAuthStore();
const chatUnread = useChatUnreadStore();

onMounted(() => {
  notifications.bind();
  notifications.refresh();
  presence.bind();
  chatUnread.bind(() => auth.account?.id ?? "");
});
</script>

<template>
  <div class="min-h-screen bg-gray-100 dark:bg-gray-950">
    <!-- Soft brand glow behind the chrome (decorative, dark mode only). -->
    <div
      aria-hidden="true"
      class="pointer-events-none fixed inset-x-0 top-0 -z-0 hidden h-80 bg-[radial-gradient(60%_100%_at_50%_0%,rgba(106,0,244,0.16),transparent_70%)] dark:block"
    />
    <AppNavbar />

    <!-- Mobile sidebar drawer -->
    <Transition name="fade">
      <div
        v-if="ui.sidebarOpen"
        class="fixed inset-0 z-40 bg-gray-950/50 backdrop-blur-sm lg:hidden"
        @click="ui.sidebarOpen = false"
      >
        <aside
          ref="drawer"
          role="dialog"
          aria-modal="true"
          :aria-label="t('nav.menu')"
          tabindex="-1"
          class="drawer h-full w-[18rem] overflow-y-auto border-e border-gray-200 bg-gray-50 pt-16 shadow-pop dark:border-gray-800 dark:bg-gray-950"
          @click.stop
        >
          <LeftSidebar />
        </aside>
      </div>
    </Transition>

    <div class="relative mx-auto flex w-full max-w-[1600px] gap-5 px-2 pt-16 sm:px-4 xl:px-6">
      <!-- Start rail (desktop) -->
      <aside class="sticky top-16 hidden h-[calc(100vh-4rem)] w-60 shrink-0 overflow-y-auto pt-3 lg:block xl:w-64">
        <LeftSidebar />
      </aside>

      <!-- Center -->
      <main class="min-w-0 flex-1 pb-28 pt-4 lg:pb-10">
        <slot />
      </main>

      <!-- End rail (wide desktop) -->
      <aside
        v-if="right"
        class="sticky top-16 hidden h-[calc(100vh-4rem)] w-80 shrink-0 overflow-y-auto pt-4 xl:block"
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
  transition: opacity 0.2s ease;
}
.fade-enter-active .drawer,
.fade-leave-active .drawer {
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
.fade-enter-from .drawer,
.fade-leave-to .drawer {
  transform: translateX(100%);
}
.fade-enter-from .drawer:dir(ltr),
.fade-leave-to .drawer:dir(ltr) {
  transform: translateX(-100%);
}
</style>
