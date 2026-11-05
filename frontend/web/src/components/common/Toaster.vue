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
function runAction(t: Toast) {
  toasts.dismiss(t.id);
  t.action?.run();
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
        class="pointer-events-auto flex w-full max-w-sm items-center gap-3 rounded-2xl border border-white/10 bg-ink/95 px-4 py-3 text-sm font-medium text-white shadow-pop ring-1 ring-brand-500/20 backdrop-blur-xl"
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
          v-if="t.action"
          type="button"
          class="shrink-0 rounded-lg px-2 py-1 font-semibold text-brand-200 transition hover:bg-white/10 hover:text-white"
          :data-testid="t.action.testid"
          @click="runAction(t)"
        >
          {{ t.action.label }}
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
