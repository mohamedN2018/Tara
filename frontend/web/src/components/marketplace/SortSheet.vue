<script setup lang="ts">
// Sort control (ported from QTech's SortSheet.vue): one list, two presentations.
// A coarse pointer gets a bottom sheet (the thumb is already at the bottom of
// the screen); a mouse gets a menu under the trigger. Unlike the original, the
// labels come from i18n and the sheet traps focus.
import { Check, SlidersHorizontal, X } from "lucide-vue-next";
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { useFocusTrap } from "@/lib/useFocusTrap";

const props = defineProps<{ options: { key: string; label: string }[]; modelValue: string }>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
const { t } = useI18n();

const open = ref(false);
const root = ref<HTMLElement | null>(null);
const menu = ref<HTMLElement | null>(null);
const sheet = ref<HTMLElement | null>(null);
useFocusTrap(sheet);

// Read once on mount rather than bound to width: a narrow desktop window is
// still a mouse, and should still get the menu.
const touch = ref(false);
const current = computed(
  () => props.options.find((o) => o.key === props.modelValue)?.label ?? "",
);

function onOutside(e: PointerEvent) {
  if (!open.value) return;
  const target = e.target as Node;
  if (root.value?.contains(target) || menu.value?.contains(target) || sheet.value?.contains(target)) {
    return;
  }
  open.value = false;
}
function onKey(e: KeyboardEvent) {
  if (e.key === "Escape" && open.value) {
    open.value = false;
    root.value?.querySelector("button")?.focus();
  }
}

onMounted(() => {
  try {
    touch.value = window.matchMedia("(pointer: coarse)").matches;
  } catch {
    touch.value = false;
  }
  document.addEventListener("pointerdown", onOutside, true);
  document.addEventListener("keydown", onKey);
});

// The sheet covers the page, so the page behind it must not scroll.
let locked = false;
function lock() {
  if (locked || !touch.value) return;
  document.body.style.overflow = "hidden";
  locked = true;
}
function unlock() {
  if (!locked) return;
  document.body.style.overflow = "";
  locked = false;
}
onUnmounted(() => {
  document.removeEventListener("pointerdown", onOutside, true);
  document.removeEventListener("keydown", onKey);
  unlock();
});

watch(open, async (v) => {
  if (!v) return unlock();
  lock();
  await nextTick();
  if (!touch.value) {
    menu.value?.querySelector<HTMLElement>('[aria-selected="true"], button')?.focus();
  }
});

function pick(key: string) {
  emit("update:modelValue", key);
  open.value = false;
}
</script>

<template>
  <div ref="root" class="relative">
    <button
      type="button"
      class="chip min-h-9 text-xs"
      :aria-expanded="open"
      aria-haspopup="listbox"
      :aria-label="t('market.sort.label', { current })"
      @click="open = !open"
    >
      <SlidersHorizontal class="h-3.5 w-3.5" aria-hidden="true" />
      <span>{{ current }}</span>
    </button>

    <!-- desktop: a menu anchored to the trigger -->
    <div
      v-if="open && !touch"
      ref="menu"
      role="listbox"
      :aria-label="t('market.sort.title')"
      class="popover absolute end-0 z-40 mt-2 min-w-[13rem] overflow-hidden"
    >
      <button
        v-for="o in options"
        :key="o.key"
        type="button"
        role="option"
        :aria-selected="o.key === modelValue"
        class="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-start text-sm transition hover:bg-brand-50 dark:hover:bg-brand-950/40"
        :class="o.key === modelValue ? 'font-bold text-brand-600 dark:text-brand-300' : 'text-gray-700 dark:text-gray-200'"
        @click="pick(o.key)"
      >
        <span>{{ o.label }}</span>
        <Check v-if="o.key === modelValue" class="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  </div>

  <!-- touch: a bottom sheet, teleported so no ancestor's overflow can clip it -->
  <Teleport to="body">
    <div
      v-if="open && touch"
      class="fixed inset-0 z-[60] flex items-end bg-gray-950/50"
      @click="open = false"
    >
      <div
        ref="sheet"
        role="dialog"
        aria-modal="true"
        :aria-label="t('market.sort.title')"
        tabindex="-1"
        class="card w-full animate-pop-in rounded-b-none rounded-t-3xl pb-[calc(1rem+env(safe-area-inset-bottom,0px))] pt-2"
        @click.stop
      >
        <span class="mx-auto mb-3 block h-1 w-9 rounded-full bg-gray-300 dark:bg-gray-700" aria-hidden="true" />
        <div class="flex items-center justify-between px-5 pb-1">
          <p class="section-title">{{ t("market.sort.title") }}</p>
          <button
            type="button"
            class="icon-btn h-8 w-8"
            :aria-label="t('market.close')"
            @click="open = false"
          >
            <X class="h-4 w-4" />
          </button>
        </div>
        <button
          v-for="o in options"
          :key="o.key"
          type="button"
          :aria-pressed="o.key === modelValue"
          class="flex w-full items-center justify-between gap-3 px-5 py-3.5 text-start text-[0.95rem]"
          :class="o.key === modelValue ? 'font-bold text-brand-600 dark:text-brand-300' : 'text-gray-700 dark:text-gray-200'"
          @click="pick(o.key)"
        >
          <span>{{ o.label }}</span>
          <Check v-if="o.key === modelValue" class="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  </Teleport>
</template>
