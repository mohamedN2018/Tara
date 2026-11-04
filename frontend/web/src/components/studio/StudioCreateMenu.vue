<script setup lang="ts">
import { CalendarClock, ChevronDown, PenSquare } from "lucide-vue-next";
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { defaultSlot } from "@/lib/planner";

// "Create post ▾": a post now, or one already set for later (the composer's
// schedule picker opens filled with the next whole hour, which the author can change).
const emit = defineEmits<{ create: [scheduleAt: string | null] }>();
const { t } = useI18n();

const open = ref(false);
const root = ref<HTMLElement | null>(null);
const firstItem = ref<HTMLButtonElement | null>(null);

async function toggle() {
  open.value = !open.value;
  if (open.value) {
    await nextTick();
    firstItem.value?.focus();
  }
}

function pick(scheduled: boolean) {
  open.value = false;
  emit("create", scheduled ? defaultSlot(new Date()).toISOString() : null);
}

function onDocument(e: Event) {
  if (open.value && root.value && !root.value.contains(e.target as Node)) open.value = false;
}
function onKey(e: KeyboardEvent) {
  if (e.key === "Escape" && open.value) open.value = false;
}
onMounted(() => {
  document.addEventListener("click", onDocument);
  window.addEventListener("keydown", onKey);
});
onBeforeUnmount(() => {
  document.removeEventListener("click", onDocument);
  window.removeEventListener("keydown", onKey);
});
</script>

<template>
  <div ref="root" class="relative">
    <button
      type="button"
      class="btn-primary w-full"
      aria-haspopup="menu"
      :aria-expanded="open"
      data-testid="studio-create"
      @click="toggle"
    >
      <span>{{ t("studio.create.button") }}</span>
      <ChevronDown class="h-4 w-4 transition" :class="open && 'rotate-180'" aria-hidden="true" />
    </button>
    <div
      v-if="open"
      role="menu"
      :aria-label="t('studio.create.menu')"
      class="popover absolute inset-x-0 bottom-full z-20 mb-2 p-1.5"
      data-testid="studio-create-menu"
    >
      <button ref="firstItem" type="button" role="menuitem" class="btn-ghost w-full justify-start" data-testid="studio-create-post" @click="pick(false)">
        <PenSquare class="h-5 w-5 text-brand-500" aria-hidden="true" />
        {{ t("studio.create.post") }}
      </button>
      <button type="button" role="menuitem" class="btn-ghost w-full justify-start" data-testid="studio-create-scheduled" @click="pick(true)">
        <CalendarClock class="h-5 w-5 text-accent-500" aria-hidden="true" />
        {{ t("studio.create.scheduled") }}
      </button>
    </div>
  </div>
</template>
