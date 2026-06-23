import { defineStore } from "pinia";
import { ref } from "vue";

import { type Locale, setLocale } from "@/i18n";

export type Theme = "light" | "dark" | "system";

function applyTheme(theme: Theme) {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const dark = theme === "dark" || (theme === "system" && prefersDark);
  document.documentElement.classList.toggle("dark", dark);
}

export const useUiStore = defineStore("ui", () => {
  const theme = ref<Theme>((localStorage.getItem("tara.theme") as Theme | null) ?? "system");
  const locale = ref<Locale>((localStorage.getItem("tara.locale") as Locale | null) ?? "ar");
  const online = ref(true);
  const sidebarOpen = ref(false);

  function setTheme(value: Theme) {
    theme.value = value;
    localStorage.setItem("tara.theme", value);
    applyTheme(value);
  }

  function changeLocale(value: Locale) {
    locale.value = value;
    setLocale(value);
  }

  function init() {
    applyTheme(theme.value);
    setLocale(locale.value);
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", () => applyTheme(theme.value));
  }

  return { theme, locale, online, sidebarOpen, setTheme, changeLocale, init };
});
