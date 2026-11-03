// Runs before the app bundle so the first paint already has the right theme
// and direction. Mirrors src/stores/ui.ts: dark is the default experience.
(function () {
  var root = document.documentElement;
  var theme = "dark";
  var locale = "ar";
  try {
    theme = localStorage.getItem("tara.theme") || "dark";
    locale = localStorage.getItem("tara.locale") || "ar";
  } catch {
    /* storage blocked: keep the defaults */
  }
  var dark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  root.classList.toggle("dark", dark);
  root.lang = locale;
  root.dir = locale === "ar" ? "rtl" : "ltr";
})();
