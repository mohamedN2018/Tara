import { defineStore } from "pinia";
import { ref } from "vue";

import { type Locale, setLocale, storedLocale } from "@/i18n";
import { identityService } from "@/services/identity";
import type { Account } from "@/types";

export type Theme = "light" | "dark" | "system";

function applyTheme(theme: Theme) {
  // matchMedia is missing in some embedded/test browsers: treat it as light.
  const prefersDark = typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const dark = theme === "dark" || (theme === "system" && prefersDark);
  document.documentElement.classList.toggle("dark", dark);
  // Keep the browser chrome (mobile address bar, PWA title bar) on-brand.
  document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]').forEach((meta) => {
    meta.content = dark ? "#0B0B1F" : "#F1F0FB";
  });
}

const THEMES: Theme[] = ["light", "dark", "system"];
function storedTheme(): Theme {
  try {
    const saved = localStorage.getItem("tara.theme") as Theme | null;
    return saved && THEMES.includes(saved) ? saved : "dark";
  } catch {
    return "dark";
  }
}

// The account is the single source of truth for language and theme: every
// choice made while signed in is saved to it, and every sign-in or boot takes
// the account's values. The only local exception is a choice not saved yet
// (made while signed out, e.g. on the login page, or whose save failed): it is
// kept here as "pending", wins once, and is then saved to the account. This is
// read on every call, never once at load, since setLocale() writes
// tara.locale on every boot.
type Prefs = { language?: Locale; theme?: Theme };
const PENDING_KEY = "tara.prefs.pending";

function readPending(): Prefs {
  try {
    const raw = JSON.parse(localStorage.getItem(PENDING_KEY) || "{}") as Prefs;
    const out: Prefs = {};
    if (raw.language === "ar" || raw.language === "en") out.language = raw.language;
    if (raw.theme && THEMES.includes(raw.theme)) out.theme = raw.theme;
    return out;
  } catch {
    return {};
  }
}
function writePending(prefs: Prefs) {
  try {
    if (prefs.language || prefs.theme) localStorage.setItem(PENDING_KEY, JSON.stringify(prefs));
    else localStorage.removeItem(PENDING_KEY);
  } catch {
    // Storage blocked: nothing to remember across pages.
  }
}

/** Text size and reduced motion: conveniences of this browser (Settings > Display). */
export type TextSize = "small" | "normal" | "large" | "xlarge";
const TEXT_SIZES: TextSize[] = ["small", "normal", "large", "xlarge"];
const TEXT_SCALE: Record<TextSize, string> = { small: "93.75%", normal: "100%", large: "112.5%", xlarge: "125%" };

function readLocal<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const saved = localStorage.getItem(key) as T | null;
    return saved && allowed.includes(saved) ? saved : fallback;
  } catch {
    return fallback;
  }
}
function writeLocal(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Storage blocked: the choice lasts for this page.
  }
}

export const useUiStore = defineStore("ui", () => {
  // Dark is Tara's primary experience; light and system are opt-in.
  const theme = ref<Theme>(storedTheme());
  const locale = ref<Locale>(storedLocale());
  const textSize = ref<TextSize>(readLocal("tara.textSize", TEXT_SIZES, "normal"));
  const reduceMotion = ref(readLocal("tara.reduceMotion", ["on", "off"] as const, "off") === "on");
  const online = ref(true);
  const sidebarOpen = ref(false);
  // Set by "Create post" shortcuts; the home composer opens and clears it.
  const composeRequested = ref(false);
  function requestCompose() {
    sidebarOpen.value = false;
    composeRequested.value = true;
  }

  // ---- server sync (PATCH /me/) -------------------------------------------
  // Set by the auth store once an account is signed in; null when signed out.
  let signedIn = false;
  let chain: Promise<unknown> = Promise.resolve();

  function queueSync(change: Prefs) {
    // Remembered until the account has it: signed out, or a save that fails.
    writePending({ ...readPending(), ...change });
    if (!signedIn) return;
    // Sent at once (a closing tab can't lose it) and one after another, so the
    // server ends on the last choice even after quick successive clicks.
    chain = chain
      .then(() => identityService.updateAccount(change))
      .then(() => {
        // Saved: forget it unless a newer choice for the same field is waiting.
        const pending = readPending();
        if (change.language && pending.language === change.language) delete pending.language;
        if (change.theme && pending.theme === change.theme) delete pending.theme;
        writePending(pending);
      })
      .catch(() => {
        // Best effort: it stays pending and is sent again at the next sign-in.
      });
  }

  function setTheme(value: Theme) {
    theme.value = value;
    writeLocal("tara.theme", value);
    applyTheme(value);
    queueSync({ theme: value });
  }

  function changeLocale(value: Locale) {
    locale.value = value;
    setLocale(value);
    queueSync({ language: value });
  }

  /**
   * Called with the signed-in account (GET /me/) and with null on sign-out.
   * The account's language and theme ("system" included) replace this
   * browser's, except a choice still pending here, which is saved instead.
   */
  function applyAccount(account: Pick<Account, "language" | "theme"> | null) {
    signedIn = !!account;
    if (!account) return;
    const pending = readPending();
    const language = account.language === "ar" || account.language === "en" ? account.language : null;
    const serverTheme = THEMES.includes(account.theme as Theme) ? (account.theme as Theme) : null;
    if (pending.language === language) delete pending.language;
    if (pending.theme === serverTheme) delete pending.theme;
    writePending(pending);
    if (!pending.language && language && language !== locale.value) {
      locale.value = language;
      setLocale(language);
    }
    if (!pending.theme && serverTheme && serverTheme !== theme.value) {
      theme.value = serverTheme;
      writeLocal("tara.theme", serverTheme);
      applyTheme(serverTheme);
    }
    if (pending.language || pending.theme) queueSync(pending);
  }

  function applyTextSize(value: TextSize) {
    document.documentElement.style.fontSize = TEXT_SCALE[value];
  }
  function applyReduceMotion(value: boolean) {
    document.documentElement.classList.toggle("reduce-motion", value);
  }
  function setTextSize(value: TextSize) {
    textSize.value = value;
    writeLocal("tara.textSize", value);
    applyTextSize(value);
  }
  function setReduceMotion(value: boolean) {
    reduceMotion.value = value;
    writeLocal("tara.reduceMotion", value ? "on" : "off");
    applyReduceMotion(value);
  }

  function init() {
    applyTheme(theme.value);
    setLocale(locale.value);
    if (textSize.value !== "normal") applyTextSize(textSize.value);
    if (reduceMotion.value) applyReduceMotion(true);
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", () => applyTheme(theme.value));
  }

  return {
    theme,
    locale,
    textSize,
    reduceMotion,
    online,
    sidebarOpen,
    composeRequested,
    requestCompose,
    setTheme,
    changeLocale,
    applyAccount,
    setTextSize,
    setReduceMotion,
    init,
  };
});
