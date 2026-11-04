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
  // Arabic gets the Arabic logo; any other language gets the English one (src/lib/brand.ts).
  var arabic = locale === "ar";
  var favicon = document.getElementById("tara-favicon");
  var apple = document.getElementById("tara-apple-icon");
  if (favicon) favicon.setAttribute("href", arabic ? "/icons/favicon-ar.png" : "/icons/favicon-en.png");
  if (apple) apple.setAttribute("href", arabic ? "/icons/apple-touch-icon.png" : "/icons/apple-touch-icon-en.png");
})();
