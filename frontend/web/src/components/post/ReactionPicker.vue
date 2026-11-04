<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";

import { REACTIONS } from "@/lib/reactions";

/**
 * The reaction bar shared by posts and comments: it opens on hover (desktop),
 * on a long press (touch) or with ArrowUp on the trigger (keyboard), and emits
 * the picked type. A plain click on the trigger is `toggle` (like / un-react).
 * The trigger is the default slot; bind the handlers it receives.
 */
const props = withDefaults(defineProps<{ small?: boolean }>(), { small: false });
const emit = defineEmits<{ pick: [type: string]; toggle: [] }>();
const { t } = useI18n();

const open = ref(false);
const bar = ref<HTMLElement | null>(null);
let openTimer: number | undefined;
let closeTimer: number | undefined;
let pressTimer: number | undefined;
let suppressClick = false;

function openSoon() {
  window.clearTimeout(closeTimer);
  openTimer = window.setTimeout(() => (open.value = true), 300);
}
function closeSoon() {
  window.clearTimeout(openTimer);
  closeTimer = window.setTimeout(() => (open.value = false), 250);
}
function cancelClose() {
  window.clearTimeout(closeTimer);
}
function choose(type: string) {
  open.value = false;
  emit("pick", type);
}
function onClick() {
  if (suppressClick) {
    suppressClick = false;
    return;
  }
  emit("toggle");
}
function onTouchstart() {
  pressTimer = window.setTimeout(() => {
    open.value = true;
    suppressClick = true;
  }, 400);
}
function onTouchend() {
  window.clearTimeout(pressTimer);
}
async function onKeydown(e: KeyboardEvent) {
  if (e.key !== "ArrowUp") return;
  e.preventDefault();
  open.value = true;
  await nextTick();
  bar.value?.querySelector<HTMLElement>("button")?.focus();
}
function onBarKeydown(e: KeyboardEvent) {
  const buttons = [...(bar.value?.querySelectorAll<HTMLElement>("button") ?? [])];
  const i = buttons.indexOf(document.activeElement as HTMLElement);
  if (e.key === "Escape") {
    e.preventDefault();
    e.stopPropagation();
    open.value = false;
    return;
  }
  const rtl = document.documentElement.dir === "rtl";
  const step = e.key === "ArrowRight" ? (rtl ? -1 : 1) : e.key === "ArrowLeft" ? (rtl ? 1 : -1) : 0;
  if (!step || i < 0) return;
  e.preventDefault();
  buttons[(i + step + buttons.length) % buttons.length]?.focus();
}

onBeforeUnmount(() => {
  window.clearTimeout(openTimer);
  window.clearTimeout(closeTimer);
  window.clearTimeout(pressTimer);
});
defineExpose({ open });
</script>

<template>
  <div class="relative" @mouseenter="openSoon" @mouseleave="closeSoon">
    <div v-if="open" class="fixed inset-0 z-40" aria-hidden="true" @click="open = false" />
    <div
      v-if="open"
      ref="bar"
      role="toolbar"
      :aria-label="t('postsFeed.reactions.pick')"
      class="absolute bottom-full start-0 z-50 mb-2 flex animate-pop-in items-center rounded-full border border-gray-200 bg-white shadow-pop dark:border-gray-700 dark:bg-gray-800"
      :class="props.small ? 'gap-1 px-2 py-1.5' : 'gap-1.5 px-3 py-2'"
      data-testid="reaction-picker"
      @mouseenter="cancelClose"
      @mouseleave="closeSoon"
      @keydown="onBarKeydown"
    >
      <button
        v-for="r in REACTIONS"
        :key="r.key"
        type="button"
        class="leading-none transition hover:-translate-y-1 hover:scale-125 focus:outline-none focus-visible:scale-125 focus-visible:ring-2 focus-visible:ring-brand-400 rounded-full"
        :class="props.small ? 'text-xl' : 'text-2xl'"
        :title="t(r.labelKey)"
        :aria-label="t(r.labelKey)"
        @click="choose(r.key)"
      >
        {{ r.emoji }}
      </button>
    </div>
    <slot :on-click="onClick" :on-touchstart="onTouchstart" :on-touchend="onTouchend" :on-keydown="onKeydown" />
  </div>
</template>
