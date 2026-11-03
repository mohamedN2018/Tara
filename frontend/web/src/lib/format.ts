import { i18n } from "@/i18n";

// NOTE: media display URLs are presigned and per-id — resolve them via
// useMediaUrl()/mediaService.resolveUrl(), not a static path.

/** Deterministic avatar fallback color from a stable key. */
export function avatarColor(key: string): string {
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = key.charCodeAt(i) + ((hash << 5) - hash);
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue} 60% 45%)`;
}

export function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

/** Compact relative time, localized to the active locale. */
export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = new Date().getTime();
  const diff = Math.round((then - now) / 1000);
  const rtf = new Intl.RelativeTimeFormat(i18n.global.locale.value, { numeric: "auto" });
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31536000],
    ["month", 2592000],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
    ["second", 1],
  ];
  for (const [unit, secs] of units) {
    if (Math.abs(diff) >= secs || unit === "second") {
      return rtf.format(Math.round(diff / secs), unit);
    }
  }
  return "";
}
