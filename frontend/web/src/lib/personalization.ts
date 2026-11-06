// The viewer's "Turn off personalization" switch on this tab (Tara Intelligence R4,
// owner decisions 8 and 24). Feed owns the preference; while it is on, `lib/signals.ts`
// queues nothing and sends nothing (impressions, dwell, opens, video and profile visits),
// and the queued batch is dropped. Home's first page carries it too (`meta`).
import { feedService } from "@/services/feed";

import { setPersonalizationOff } from "./signals";

/** Read the preference and apply it; null when the server could not say. */
export async function syncPersonalization(): Promise<boolean | null> {
  try {
    const prefs = await feedService.preferences();
    if (typeof prefs.personalization_off !== "boolean") return null;
    setPersonalizationOff(prefs.personalization_off);
    return prefs.personalization_off;
  } catch {
    return null;
  }
}
