import { defineStore } from "pinia";
import { ref } from "vue";

import { type Locale, setLocale } from "@/i18n";

export type Theme = "light" | "dark" | "system";

function applyTheme(theme: Theme) {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const dark = theme === "dark" || (theme === "system" && prefersDark);
  document.documentElement.classList.toggle("dark", dark);
  // Keep the browser chrome (mobile address bar, PWA title bar) on-brand.
  document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]').forEach((meta) => {
    meta.content = dark ? "#0B0B1F" : "#F1F0FB";
  });
}

export const useUiStore = defineStore("ui", () => {
  // Dark is Tara's primary experience; light and system are opt-in.
  const theme = ref<Theme>((localStorage.getItem("tara.theme") as Theme | null) ?? "dark");
  const locale = ref<Locale>((localStorage.getItem("tara.locale") as Locale | null) ?? "ar");
  const online = ref(true);
  const sidebarOpen = ref(false);
  // Set by "Create post" shortcuts; the home composer opens and clears it.
  const composeRequested = ref(false);
  function requestCompose() {
    sidebarOpen.value = false;
    composeRequested.value = true;
  }

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

  return {
    theme,
    locale,
    online,
    sidebarOpen,
    composeRequested,
    requestCompose,
    setTheme,
    changeLocale,
    init,
  };
});
