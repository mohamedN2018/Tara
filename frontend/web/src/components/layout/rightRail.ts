import { ref, shallowRef } from "vue";

import { eventsService, type TaraEvent } from "@/services/events";
import type { SponsoredSlot } from "@/types";

/**
 * The sponsored slot the right column shows. The home feed fills it with the
 * slot it was served (ads have no other client-facing placement), and clears it
 * when there is none, so the column never renders an empty ad card.
 */
export const railAd = shallowRef<SponsoredSlot | null>(null);

export function setRailAd(slot: SponsoredSlot | null | undefined): void {
  railAd.value = slot && slot.creative_id && slot.headline ? slot : null;
}

/** The right column shows from Tailwind's `xl` breakpoint (AppShell's `xl:block`). */
export const RAIL_MEDIA = "(min-width: 1280px)";

/**
 * Whether the right column is on screen. The first ad goes either to the
 * column (wide screens) or into the feed, never both, so it is mounted once.
 */
export const railVisible = ref(false);
try {
  const query = window.matchMedia(RAIL_MEDIA);
  railVisible.value = query.matches;
  query.addEventListener?.("change", (e) => (railVisible.value = e.matches));
} catch {
  // No matchMedia (tests, very old browsers): the ad stays in the feed.
}

export const MAX_RAIL_EVENTS = 3;

/**
 * "Your upcoming events": what the viewer is going to or interested in, plus
 * what they host (hosts are not RSVPed automatically), soonest first.
 */
export async function upcomingEvents(limit = MAX_RAIL_EVENTS): Promise<TaraEvent[]> {
  const [going, hosting] = await Promise.all([
    eventsService.list("going").then((p) => p.data).catch(() => []),
    eventsService.list("hosting").then((p) => p.data).catch(() => []),
  ]);
  const byId = new Map<string, TaraEvent>();
  for (const e of [...going, ...hosting]) if (e.status !== "cancelled") byId.set(e.id, e);
  return [...byId.values()].sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at)).slice(0, limit);
}
