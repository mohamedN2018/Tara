<script setup lang="ts">
// Display and accessibility. Theme and language are account preferences
// (PATCH /me/ through the ui store, so they follow the account to other
// devices); text size and reduced motion belong to this browser.
import { useI18n } from "vue-i18n";

import type { Locale } from "@/i18n";
import { canInstall, installApp } from "@/lib/pwa";
import { type TextSize, type Theme, useUiStore } from "@/stores/ui";

import SettingSwitch from "./SettingSwitch.vue";

const { t } = useI18n();
const ui = useUiStore();

const THEMES: Theme[] = ["light", "dark", "system"];
const LOCALES: { value: Locale; label: string }[] = [
  { value: "ar", label: "العربية" },
  { value: "en", label: "English" },
];
const SIZES: TextSize[] = ["small", "normal", "large", "xlarge"];

const chip = (on: boolean) =>
  ["chip cursor-pointer focus-within:ring-2 focus-within:ring-brand-400", on ? "chip-active" : ""];
</script>

<template>
  <section id="theme" class="card mb-4 scroll-mt-20 p-4" data-testid="display-settings">
    <fieldset class="mb-4">
      <legend class="mb-1 font-semibold">{{ t("settingsCenter.display.theme") }}</legend>
      <p class="mb-2 text-xs text-gray-500 dark:text-gray-400">{{ t("settingsCenter.display.themeHint") }}</p>
      <div class="flex flex-wrap gap-2">
        <label v-for="th in THEMES" :key="th" :class="chip(ui.theme === th)">
          <input type="radio" name="display-theme" class="sr-only" :value="th" :checked="ui.theme === th" :data-testid="`display-theme-${th}`" @change="ui.setTheme(th)" />
          {{ t(`settings.${th}`) }}
        </label>
      </div>
    </fieldset>

    <fieldset id="language" class="mb-4 scroll-mt-20">
      <legend class="mb-2 font-semibold">{{ t("settingsCenter.display.language") }}</legend>
      <div class="flex flex-wrap gap-2">
        <label v-for="l in LOCALES" :key="l.value" :class="chip(ui.locale === l.value)" :lang="l.value">
          <input type="radio" name="display-locale" class="sr-only" :value="l.value" :checked="ui.locale === l.value" :data-testid="`display-locale-${l.value}`" @change="ui.changeLocale(l.value)" />
          {{ l.label }}
        </label>
      </div>
    </fieldset>

    <fieldset class="mb-4">
      <legend class="mb-1 font-semibold">{{ t("settingsCenter.display.textSize") }}</legend>
      <p class="mb-2 text-xs text-gray-500 dark:text-gray-400">{{ t("settingsCenter.display.textSizeHint") }}</p>
      <div class="flex flex-wrap gap-2">
        <label v-for="s in SIZES" :key="s" :class="chip(ui.textSize === s)">
          <input type="radio" name="display-size" class="sr-only" :value="s" :checked="ui.textSize === s" @change="ui.setTextSize(s)" />
          {{ t(`settingsCenter.display.textSizes.${s}`) }}
        </label>
      </div>
    </fieldset>

    <SettingSwitch
      :model-value="ui.reduceMotion"
      :label="t('settingsCenter.display.reduceMotion')"
      :hint="t('settingsCenter.display.reduceMotionHint')"
      testid="toggle-reduce-motion"
      @update:model-value="ui.setReduceMotion"
    />

    <div v-if="canInstall" class="mt-2 flex items-center justify-between border-t border-gray-100 pt-3 dark:border-gray-800">
      <span class="text-sm">{{ t("settings.installApp") }}</span>
      <button type="button" class="btn-primary text-sm" @click="installApp">{{ t("settings.install") }}</button>
    </div>
  </section>
</template>
