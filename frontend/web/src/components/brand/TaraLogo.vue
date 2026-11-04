<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { brandAppIcon, brandMark, isArabicLocale } from "@/lib/brand";

/**
 * The Tara logo, in the interface language: the Arabic wordmark "تارا" for
 * Arabic, the English logo ("Tara") for any other language. Both already
 * spell the name, so no text is added next to them.
 * - `mark` / `full`: the logo (kept as two names for existing callers).
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
const isIcon = computed(() => props.variant === "icon");
const light = computed(() => (isIcon.value ? brandAppIcon(locale.value) : brandMark(locale.value, props.tone)));
const dark = computed(() =>
  isIcon.value ? brandAppIcon(locale.value) : brandMark(locale.value, props.tone, true),
);
// Wordmarks are a little wider than tall: give them a touch more height so
// they read at the same visual size as the old square mark.
const height = computed(() => (isIcon.value ? props.size : Math.round(props.size * (arabic.value ? 1.1 : 1.2))));
const style = computed(() => ({ height: `${height.value}px`, width: isIcon.value ? `${height.value}px` : undefined }));
</script>

<template>
  <span class="inline-flex shrink-0 items-center" role="img" :aria-label="label" dir="ltr">
    <img
      :src="light"
      alt=""
      aria-hidden="true"
      draggable="false"
      decoding="async"
      class="block w-auto select-none object-contain"
      :class="[isIcon ? 'rounded-[22%]' : '', dark !== light ? 'dark:hidden' : '']"
      :style="style"
    />
    <img
      v-if="dark !== light"
      :src="dark"
      alt=""
      aria-hidden="true"
      draggable="false"
      decoding="async"
      class="hidden w-auto select-none object-contain dark:block"
      :style="style"
    />
  </span>
</template>
