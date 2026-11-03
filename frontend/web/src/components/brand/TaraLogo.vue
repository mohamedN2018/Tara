<script setup lang="ts">
import { computed, useId } from "vue";

/**
 * The Tara logo system.
 * - `mark`: the geometric T with its spark, on its own.
 * - `full`: mark + "Tara" wordmark.
 * - `icon`: the app icon (gradient tile, white mark).
 * `tone` picks the mark colouring: brand gradient, solid white (on photos or
 * the gradient), or solid ink (single-colour print).
 */
const props = withDefaults(
  defineProps<{
    variant?: "mark" | "full" | "icon";
    tone?: "gradient" | "white" | "ink";
    size?: number;
    label?: string;
  }>(),
  { variant: "full", tone: "gradient", size: 32, label: "Tara" },
);

const uid = useId();
const ids = { bar: `${uid}-bar`, stem: `${uid}-stem`, star: `${uid}-star`, tile: `${uid}-tile` };

const fills = computed(() => {
  if (props.variant === "icon" || props.tone === "white") {
    return { bar: "#FFFFFF", stem: "rgba(255,255,255,0.86)", star: "#FFFFFF" };
  }
  if (props.tone === "ink") return { bar: "#0B0B1F", stem: "#0B0B1F", star: "#6A00F4" };
  return { bar: `url(#${ids.bar})`, stem: `url(#${ids.stem})`, star: `url(#${ids.star})` };
});
</script>

<template>
  <span
    class="inline-flex shrink-0 items-center gap-2"
    role="img"
    :aria-label="label"
    dir="ltr"
  >
    <svg
      :width="size"
      :height="size"
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient :id="ids.bar" x1="6" y1="22" x2="58" y2="8" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#A855F7" />
          <stop offset="1" stop-color="#FF4ED8" />
        </linearGradient>
        <linearGradient :id="ids.stem" x1="40" y1="20" x2="22" y2="60" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#8A2DF6" />
          <stop offset="1" stop-color="#6A00F4" />
        </linearGradient>
        <linearGradient :id="ids.star" x1="38" y1="31" x2="56" y2="49" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#FF4ED8" />
          <stop offset="1" stop-color="#A855F7" />
        </linearGradient>
        <linearGradient :id="ids.tile" x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#6A00F4" />
          <stop offset="0.55" stop-color="#A855F7" />
          <stop offset="1" stop-color="#FF4ED8" />
        </linearGradient>
      </defs>
      <template v-if="variant === 'icon'">
        <rect width="64" height="64" rx="15" :fill="`url(#${ids.tile})`" />
        <g transform="translate(11.2 11.2) scale(0.65)">
          <path
            d="M14.5 8H57.2a1.6 1.6 0 0 1 1.5 2.2l-3.9 9.6A3.6 3.6 0 0 1 51.5 22H6.8a1.6 1.6 0 0 1-1.5-2.2l3.9-9.6A8.4 8.4 0 0 1 14.5 8Z"
            :fill="fills.bar"
          />
          <path d="M27.4 22H41.8L31.6 54.6A7.6 7.6 0 0 1 24.4 60H18.8a1.4 1.4 0 0 1-1.3-1.8Z" :fill="fills.stem" />
          <path
            d="M47 31c.75 5.6 2.4 7.25 8 8-5.6.75-7.25 2.4-8 8-.75-5.6-2.4-7.25-8-8 5.6-.75 7.25-2.4 8-8Z"
            :fill="fills.star"
          />
        </g>
      </template>
      <template v-else>
        <path
          d="M14.5 8H57.2a1.6 1.6 0 0 1 1.5 2.2l-3.9 9.6A3.6 3.6 0 0 1 51.5 22H6.8a1.6 1.6 0 0 1-1.5-2.2l3.9-9.6A8.4 8.4 0 0 1 14.5 8Z"
          :fill="fills.bar"
        />
        <path d="M27.4 22H41.8L31.6 54.6A7.6 7.6 0 0 1 24.4 60H18.8a1.4 1.4 0 0 1-1.3-1.8Z" :fill="fills.stem" />
        <path
          d="M47 31c.75 5.6 2.4 7.25 8 8-5.6.75-7.25 2.4-8 8-.75-5.6-2.4-7.25-8-8 5.6-.75 7.25-2.4 8-8Z"
          :fill="fills.star"
        />
      </template>
    </svg>
    <span
      v-if="variant === 'full'"
      class="font-display font-extrabold leading-none tracking-tight"
      :class="tone === 'white' ? 'text-white' : tone === 'ink' ? 'text-ink' : 'text-gray-950 dark:text-white'"
      :style="{ fontSize: `${Math.round(size * 0.78)}px`, letterSpacing: '-0.03em' }"
    >Tara</span>
  </span>
</template>
