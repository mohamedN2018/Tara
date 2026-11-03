<script setup lang="ts">
// Read-only stars, or a 1-5 picker (a radio group, so arrow keys work).
import { Star } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

const props = withDefaults(
  defineProps<{ value: number | null; editable?: boolean; size?: number }>(),
  { editable: false, size: 16 },
);
const emit = defineEmits<{ "update:value": [value: number] }>();
const { t } = useI18n();

function onKey(e: KeyboardEvent, n: number) {
  // Logical direction: in RTL the "next" star is to the left.
  const rtl = document.documentElement.dir === "rtl";
  const forward = rtl ? "ArrowLeft" : "ArrowRight";
  const back = rtl ? "ArrowRight" : "ArrowLeft";
  if (e.key === forward || e.key === "ArrowUp") emit("update:value", Math.min(5, n + 1));
  else if (e.key === back || e.key === "ArrowDown") emit("update:value", Math.max(1, n - 1));
  else return;
  e.preventDefault();
}
</script>

<template>
  <div
    v-if="editable"
    role="radiogroup"
    :aria-label="t('market.reviews.yourRating')"
    class="inline-flex gap-1"
  >
    <button
      v-for="n in 5"
      :key="n"
      type="button"
      role="radio"
      :aria-checked="props.value === n"
      :aria-label="t('market.reviews.stars', n)"
      :tabindex="(props.value ?? 1) === n ? 0 : -1"
      class="rounded p-0.5 text-amber-400 transition hover:scale-110 focus-visible:ring-2 focus-visible:ring-brand-400"
      @click="emit('update:value', n)"
      @keydown="onKey($event, n)"
    >
      <Star :size="size + 8" :fill="(props.value ?? 0) >= n ? 'currentColor' : 'none'" />
    </button>
  </div>
  <span
    v-else
    class="inline-flex items-center gap-0.5 text-amber-400"
    role="img"
    :aria-label="t('market.reviews.ratingOf', { n: (props.value ?? 0).toFixed(1) })"
  >
    <Star
      v-for="n in 5"
      :key="n"
      :size="size"
      :fill="(props.value ?? 0) >= n - 0.25 ? 'currentColor' : 'none'"
      aria-hidden="true"
    />
  </span>
</template>
