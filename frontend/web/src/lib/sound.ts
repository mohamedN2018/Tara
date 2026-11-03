// A short notification "ping" synthesised with Web Audio (no asset to download).
// Ported from QTech's utils/sound.js. Differences: it is OFF unless the user turns
// it on (a per-device setting), and it stays silent during the user's quiet hours.
//
// Browsers block audio until the page has had a user gesture, so the context is
// unlocked on the first pointer or key press; a ping before that is skipped.

const STORAGE_KEY = "tara.notifications.sound";
const MIN_GAP_SECONDS = 0.25; // a burst of events makes one ping, not ten

type AudioCtor = typeof AudioContext;
let ctx: AudioContext | null = null;
let last = -Infinity;

function context(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (!ctx) {
    const Ctor: AudioCtor | undefined =
      window.AudioContext ?? (window as unknown as { webkitAudioContext?: AudioCtor }).webkitAudioContext;
    if (!Ctor) return null;
    try {
      ctx = new Ctor();
    } catch {
      return null;
    }
  }
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
  return ctx;
}

export function soundEnabled(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setSoundEnabled(on: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, on ? "1" : "0");
  } catch {
    // Storage unavailable (private mode): the setting lasts for this page only.
  }
  if (on) context(); // toggling is a user gesture: unlock now so the next ping plays
}

const toMinutes = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};

/** Same rule as the server (`push.in_quiet_hours`): the window may cross midnight. */
export function inQuietHours(
  quiet: { start?: string; end?: string; timezone?: string } | null | undefined,
  now: Date = new Date(),
): boolean {
  if (!quiet?.start || !quiet.end) return false;
  let hhmm: string;
  try {
    hhmm = new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      timeZone: quiet.timezone || "UTC",
    }).format(now);
  } catch {
    hhmm = `${String(now.getUTCHours()).padStart(2, "0")}:${String(now.getUTCMinutes()).padStart(2, "0")}`;
  }
  const current = toMinutes(hhmm);
  const start = toMinutes(quiet.start);
  const end = toMinutes(quiet.end);
  return start < end ? current >= start && current < end : current >= start || current < end;
}

/** Play the ping if the user wants it and it is not quiet time. Returns whether it played. */
export function playPing(quiet?: { start?: string; end?: string; timezone?: string } | null): boolean {
  if (!soundEnabled() || inQuietHours(quiet)) return false;
  const c = context();
  if (!c || c.state !== "running") return false;
  const now = c.currentTime;
  if (now - last < MIN_GAP_SECONDS) return false;
  last = now;
  const osc = c.createOscillator();
  const gain = c.createGain();
  osc.connect(gain);
  gain.connect(c.destination);
  osc.type = "sine";
  osc.frequency.setValueAtTime(880, now);
  osc.frequency.exponentialRampToValueAtTime(1320, now + 0.08);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.18, now + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.35);
  osc.start(now);
  osc.stop(now + 0.36);
  return true;
}

if (typeof window !== "undefined") {
  const unlock = () => {
    if (soundEnabled()) context();
  };
  window.addEventListener("pointerdown", unlock, { once: true });
  window.addEventListener("keydown", unlock, { once: true });
}
