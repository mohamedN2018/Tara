import { ref } from "vue";

// Ads the viewer hid with the card's X. The ads service has no endpoint for
// this yet, so it only lasts for this browser session (sessionStorage), and
// every copy of the ad (feed and right column) reads the same set.
const KEY = "tara.hiddenAds";

function read(): string[] {
  try {
    const raw = sessionStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

export const hiddenAds = ref<Set<string>>(new Set(read()));

function write(next: Set<string>) {
  hiddenAds.value = next;
  try {
    sessionStorage.setItem(KEY, JSON.stringify([...next]));
  } catch {
    // Private mode: hidden until the page reloads.
  }
}

export function hideAd(creativeId: string) {
  write(new Set(hiddenAds.value).add(creativeId));
}

export function unhideAd(creativeId: string) {
  const next = new Set(hiddenAds.value);
  next.delete(creativeId);
  write(next);
}
