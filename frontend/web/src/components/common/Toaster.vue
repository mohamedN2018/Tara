<script setup lang="ts">
import { Bell, MessageCircle, X } from "lucide-vue-next";
import { useRouter } from "vue-router";

import { type Toast, useToastStore } from "@/stores/toasts";

const toasts = useToastStore();
const router = useRouter();

function activate(t: Toast) {
  if (t.to) router.push(t.to);
  toasts.dismiss(t.id);
}
</script>

<template>
  <div class="pointer-events-none fixed inset-x-0 bottom-20 z-[70] flex flex-col items-center gap-2 px-3 lg:bottom-6 lg:items-end lg:pe-6">
    <TransitionGroup name="toast">
      <button
        v-for="t in toasts.items"
        :key="t.id"
        class="pointer-events-auto flex w-full max-w-sm items-center gap-3 rounded-xl bg-gray-900/95 px-4 py-3 text-start text-sm text-white shadow-lg backdrop-blur"
        @click="activate(t)"
      >
        <component :is="t.icon === 'message' ? MessageCircle : Bell" class="h-5 w-5 shrink-0 text-brand-300" />
        <span class="min-w-0 flex-1 truncate">{{ t.text }}</span>
        <X class="h-4 w-4 shrink-0 opacity-60 transition hover:opacity-100" @click.stop="toasts.dismiss(t.id)" />
      </button>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 0.25s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
