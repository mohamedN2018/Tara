<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { brandAppIcon, brandMark, isArabicLocale } from "@/lib/brand";

/**
 * The Tara logo, in the interface language: the Arabic wordmark "تارا" for
 * Arabic, the English "T" mark (plus the "Tara" wordmark) for any other
 * language.
 * - `mark`: the logo on its own.
 * - `full`: Arabic shows the wordmark (it already reads "تارا"); other
 *   languages show the T mark followed by "Tara".
 * - `icon`: the square app icon.
 * `tone` picks the colour artwork or the white one (on photos or gradients);
 * `size` is the logo height in pixels.
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

const { locale } = useI18n();
const arabic = computed(() => isArabicLocale(locale.value));
const src = computed(() =>
  props.variant === "icon" ? brandAppIcon(locale.value) : brandMark(locale.value, props.tone),
);
// The English T is square; the Arabic wordmark is a little wider than tall, so
// it gets a touch more height to read at the same visual size.
const height = computed(() =>
  props.variant !== "icon" && arabic.value ? Math.round(props.size * 1.1) : props.size,
);
const showWord = computed(() => props.variant === "full" && !arabic.value);
</script>

<template>
  <span class="inline-flex shrink-0 items-center gap-2" role="img" :aria-label="label" dir="ltr">
    <img
      :src="src"
      alt=""
      aria-hidden="true"
      draggable="false"
      decoding="async"
      class="block w-auto select-none object-contain"
      :class="variant === 'icon' ? 'rounded-[22%]' : ''"
      :style="{ height: `${height}px`, width: variant === 'icon' ? `${height}px` : undefined }"
    />
    <span
      v-if="showWord"
      class="font-display font-extrabold leading-none tracking-tight"
      :class="tone === 'white' ? 'text-white' : tone === 'ink' ? 'text-ink' : 'text-gray-950 dark:text-white'"
      :style="{ fontSize: `${Math.round(size * 0.78)}px`, letterSpacing: '-0.03em' }"
    >Tara</span>
  </span>
</template>
