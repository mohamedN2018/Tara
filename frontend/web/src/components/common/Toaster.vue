<script setup lang="ts">
import { AlertCircle, Bell, CheckCircle2, MessageCircle, X } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { type Toast, useToastStore } from "@/stores/toasts";

const { t: tr } = useI18n();
const toasts = useToastStore();
const router = useRouter();

const ICONS = { bell: Bell, message: MessageCircle, error: AlertCircle, success: CheckCircle2 };

function activate(t: Toast) {
  if (t.to) router.push(t.to);
  toasts.dismiss(t.id);
}
</script>

<template>
  <div
    class="pointer-events-none fixed inset-x-0 bottom-20 z-[70] flex flex-col items-center gap-2 px-3 lg:bottom-6 lg:items-end lg:pe-6"
    role="status"
    aria-live="polite"
    aria-relevant="additions"
  >
    <TransitionGroup name="toast">
      <div
        v-for="t in toasts.items"
        :key="t.id"
        class="pointer-events-auto flex w-full max-w-sm items-center gap-3 rounded-xl bg-gray-900/95 px-4 py-3 text-sm text-white shadow-lg backdrop-blur"
      >
        <button class="flex min-w-0 flex-1 items-center gap-3 text-start" @click="activate(t)">
          <component
            :is="ICONS[t.icon ?? 'bell']"
            class="h-5 w-5 shrink-0"
            :class="t.icon === 'error' ? 'text-red-400' : t.icon === 'success' ? 'text-green-400' : 'text-brand-300'"
          />
          <span class="min-w-0 flex-1 truncate" dir="auto">{{ t.text }}</span>
        </button>
        <button
          class="shrink-0 opacity-60 transition hover:opacity-100"
          :aria-label="tr('market.close')"
          @click="toasts.dismiss(t.id)"
        >
          <X class="h-4 w-4" />
        </button>
      </div>
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
