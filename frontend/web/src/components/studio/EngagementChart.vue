<script setup lang="ts">
// One series over time (the studio's "views / engagement over time"): a 2px
// line on a light area, recessive grid, a crosshair + tooltip on hover or
// arrow keys, and a table view of the same numbers. One series, so the title
// names it and there is no legend box.
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{ points: { date: string; value: number }[]; label: string }>();
const { t, locale } = useI18n();

const W = 640;
const H = 220;
// Room for the value axis on both sides: it sits on the start side in either direction.
const PAD = { top: 12, right: 40, bottom: 28, left: 40 };
const innerW = W - PAD.left - PAD.right;
const innerH = H - PAD.top - PAD.bottom;

const max = computed(() => Math.max(0, ...props.points.map((p) => p.value)));
// A "nice" top for the axis: 1, 2 or 5 times a power of ten, at least 4.
const top = computed(() => {
  const m = Math.max(4, max.value);
  const pow = 10 ** Math.floor(Math.log10(m));
  return [1, 2, 5, 10].map((k) => k * pow).find((v) => v >= m) ?? m;
});
const ticks = computed(() => [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(top.value * f)));

const isRtl = computed(() => locale.value === "ar");
const x = (i: number) => {
  const n = Math.max(1, props.points.length - 1);
  const pos = (i / n) * innerW;
  // Time runs with the reading direction.
  return PAD.left + (isRtl.value ? innerW - pos : pos);
};
const y = (v: number) => PAD.top + innerH - (v / top.value) * innerH;

const line = computed(() => props.points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" "));
const area = computed(() => {
  if (!props.points.length) return "";
  const n = props.points.length - 1;
  return `${line.value} L${x(n).toFixed(1)},${y(0)} L${x(0).toFixed(1)},${y(0)} Z`;
});

const fmtNum = (n: number) => new Intl.NumberFormat(locale.value).format(n);
const fmtDay = (iso: string, long = false) =>
  new Intl.DateTimeFormat(locale.value, long ? { dateStyle: "medium" } : { day: "numeric", month: "short" }).format(new Date(`${iso}T12:00:00`));

// A handful of date labels, evenly spread.
const xLabels = computed(() => {
  const n = props.points.length;
  if (!n) return [];
  const want = Math.min(n, 6);
  const step = (n - 1) / Math.max(1, want - 1);
  const idx = new Set(Array.from({ length: want }, (_, k) => Math.round(k * step)));
  return [...idx].map((i) => ({ i, text: fmtDay(props.points[i].date) }));
});

const active = ref<number | null>(null);
const svg = ref<SVGSVGElement | null>(null);
function onMove(e: PointerEvent) {
  const el = svg.value;
  if (!el || !props.points.length) return;
  const rect = el.getBoundingClientRect();
  const px = ((e.clientX - rect.left) / rect.width) * W;
  let pos = (px - PAD.left) / innerW;
  if (isRtl.value) pos = 1 - pos;
  active.value = Math.min(props.points.length - 1, Math.max(0, Math.round(pos * (props.points.length - 1))));
}
function onKey(e: KeyboardEvent) {
  if (!props.points.length) return;
  const fwd = isRtl.value ? "ArrowLeft" : "ArrowRight";
  const back = isRtl.value ? "ArrowRight" : "ArrowLeft";
  const cur = active.value ?? props.points.length - 1;
  if (e.key === fwd) active.value = Math.min(props.points.length - 1, cur + 1);
  else if (e.key === back) active.value = Math.max(0, cur - 1);
  else if (e.key === "Home") active.value = 0;
  else if (e.key === "End") active.value = props.points.length - 1;
  else if (e.key === "Escape") active.value = null;
  else return;
  e.preventDefault();
}
const tip = computed(() => {
  if (active.value === null) return null;
  const p = props.points[active.value];
  if (!p) return null;
  const left = (x(active.value) / W) * 100;
  return { p, left, top: (y(p.value) / H) * 100 };
});
const total = computed(() => props.points.reduce((s, p) => s + p.value, 0));
const showTable = ref(false);
</script>

<template>
  <figure class="m-0" data-testid="engagement-chart">
    <div class="relative">
      <svg
        ref="svg"
        :viewBox="`0 0 ${W} ${H}`"
        dir="ltr"
        class="block h-auto w-full touch-pan-y select-none text-brand-600 outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:text-brand-300"
        role="img"
        tabindex="0"
        :aria-label="t('polish.studio.chartAria', { metric: label, total: fmtNum(total), days: points.length })"
        @pointermove="onMove"
        @pointerleave="active = null"
        @keydown="onKey"
        @blur="active = null"
      >
        <g class="text-gray-200 dark:text-gray-800" aria-hidden="true">
          <line v-for="v in ticks" :key="v" :x1="PAD.left" :x2="W - PAD.right" :y1="y(v)" :y2="y(v)" stroke="currentColor" stroke-width="1" />
        </g>
        <g class="fill-gray-600 text-[11px] dark:fill-gray-400" aria-hidden="true">
          <text v-for="v in ticks" :key="`t${v}`" :x="isRtl ? W - PAD.right + 6 : PAD.left - 6" :y="y(v) + 4" :text-anchor="isRtl ? 'start' : 'end'" style="font-size: 11px">{{ fmtNum(v) }}</text>
          <text v-for="l in xLabels" :key="`x${l.i}`" :x="x(l.i)" :y="H - 8" text-anchor="middle" style="font-size: 11px">{{ l.text }}</text>
        </g>
        <path :d="area" fill="currentColor" fill-opacity="0.10" />
        <path :d="line" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
        <g v-if="tip" aria-hidden="true">
          <line :x1="x(active!)" :x2="x(active!)" :y1="PAD.top" :y2="PAD.top + innerH" class="text-gray-400 dark:text-gray-600" stroke="currentColor" stroke-width="1" stroke-dasharray="3 3" />
          <circle :cx="x(active!)" :cy="y(tip.p.value)" r="5" fill="currentColor" class="stroke-white dark:stroke-gray-900" stroke-width="2" />
        </g>
      </svg>
      <div
        v-if="tip"
        class="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-lg bg-gray-900 px-2.5 py-1.5 text-xs text-white shadow-pop dark:bg-gray-100 dark:text-gray-900"
        :style="{ left: `${tip.left}%`, top: `calc(${tip.top}% - 10px)` }"
        role="status"
        data-testid="engagement-tooltip"
      >
        <span class="block font-semibold">{{ fmtDay(tip.p.date, true) }}</span>
        <span>{{ label }}: {{ fmtNum(tip.p.value) }}</span>
      </div>
    </div>
    <figcaption class="mt-2 flex items-center justify-between gap-2 text-xs text-gray-600 dark:text-gray-400">
      <span>{{ t("polish.studio.chartHint") }}</span>
      <button type="button" class="font-semibold text-brand-700 hover:underline dark:text-brand-300" :aria-expanded="showTable" data-testid="engagement-table-toggle" @click="showTable = !showTable">
        {{ showTable ? t("polish.studio.hideTable") : t("polish.studio.showTable") }}
      </button>
    </figcaption>
    <div v-if="showTable" class="mt-2 max-h-64 overflow-y-auto rounded-xl ring-1 ring-gray-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:ring-gray-800" role="region" :aria-label="label" tabindex="0">
      <table class="w-full text-sm" data-testid="engagement-table">
        <caption class="sr-only">{{ label }}</caption>
        <thead class="sticky top-0 bg-gray-50 text-xs text-gray-600 dark:bg-gray-900 dark:text-gray-400">
          <tr>
            <th scope="col" class="px-3 py-2 text-start font-semibold">{{ t("polish.studio.day") }}</th>
            <th scope="col" class="px-3 py-2 text-end font-semibold">{{ label }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100 dark:divide-gray-800">
          <tr v-for="p in points" :key="p.date">
            <td class="px-3 py-1.5">{{ fmtDay(p.date, true) }}</td>
            <td class="px-3 py-1.5 text-end tabular-nums">{{ fmtNum(p.value) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </figure>
</template>
