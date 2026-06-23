import { createI18n } from "vue-i18n";

import ar from "./ar";
import en from "./en";

export type Locale = "en" | "ar";

const stored = (localStorage.getItem("tara.locale") as Locale | null) ?? "ar";

export const i18n = createI18n({
  legacy: false,
  locale: stored,
  fallbackLocale: "en",
  messages: { en, ar },
});

/** Apply locale + document direction together; persists the choice. */
export function setLocale(locale: Locale) {
  i18n.global.locale.value = locale;
  localStorage.setItem("tara.locale", locale);
  document.documentElement.lang = locale;
  document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
}
