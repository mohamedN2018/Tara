import { createI18n } from "vue-i18n";

import ar from "./ar";
import en from "./en";

export type Locale = "en" | "ar";

/** The saved language; Arabic when none (or storage is blocked, or the value is junk). */
export function storedLocale(): Locale {
  try {
    return localStorage.getItem("tara.locale") === "en" ? "en" : "ar";
  } catch {
    return "ar";
  }
}
const stored = storedLocale();

/**
 * Arabic has six plural forms, written in this order in ar.ts:
 * zero | one | two | few (3-10) | many (11-99) | other (100+, 101, 102…).
 */
export function arabicPlural(count: number): number {
  const n = Math.abs(count);
  if (n <= 2) return n;
  const lastTwo = n % 100;
  if (lastTwo >= 3 && lastTwo <= 10) return 3;
  if (lastTwo >= 11) return 4;
  return 5;
}

export const i18n = createI18n({
  legacy: false,
  locale: stored,
  fallbackLocale: "en",
  messages: { en, ar },
  pluralRules: { ar: arabicPlural },
});

/** Apply locale + document direction together; persists the choice. */
export function setLocale(locale: Locale) {
  i18n.global.locale.value = locale;
  try {
    localStorage.setItem("tara.locale", locale);
  } catch {
    // Storage blocked: the choice lasts for this page.
  }
  document.documentElement.lang = locale;
  document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
  // The service worker can't read localStorage: leave the language where it can.
  if ("caches" in window) {
    caches
      .open("tara-prefs")
      .then((cache) => cache.put("/__locale", new Response(locale)))
      .catch(() => {});
  }
}
