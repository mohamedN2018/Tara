// Tara's logo follows the interface language: Arabic gets the Arabic wordmark
// ("تارا"), every other language gets the English "T" mark. The artwork comes
// from frontend/Desgin and is exported to src/assets/brand and public/icons.
import arMark from "@/assets/brand/tara-ar.png";
import arMarkWhite from "@/assets/brand/tara-ar-white.png";
import enMark from "@/assets/brand/tara-en.png";
import enMarkWhite from "@/assets/brand/tara-en-white.png";

export type BrandTone = "gradient" | "white" | "ink";

export function isArabicLocale(locale: string | null | undefined): boolean {
  return (locale ?? "").toLowerCase().split("-")[0] === "ar";
}

/** The logo image for a language and tone ("ink" uses the colour artwork). */
export function brandMark(locale: string, tone: BrandTone = "gradient"): string {
  const arabic = isArabicLocale(locale);
  if (tone === "white") return arabic ? arMarkWhite : enMarkWhite;
  return arabic ? arMark : enMark;
}

/** The square app icon for a language. */
export function brandAppIcon(locale: string): string {
  return isArabicLocale(locale) ? "/icons/icon-ar-192.png" : "/icons/icon-en-192.png";
}

/** Swap the tab favicon and the home-screen icon to match the language. */
export function applyBrandIcons(locale: string): void {
  if (typeof document === "undefined") return;
  const arabic = isArabicLocale(locale);
  document
    .getElementById("tara-favicon")
    ?.setAttribute("href", arabic ? "/icons/favicon-ar.png" : "/icons/favicon-en.png");
  document
    .getElementById("tara-apple-icon")
    ?.setAttribute("href", arabic ? "/icons/apple-touch-icon.png" : "/icons/apple-touch-icon-en.png");
}
