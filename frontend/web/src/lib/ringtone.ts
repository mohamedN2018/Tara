// Call tones synthesised with Web Audio (no asset to download), like the
// notification ping in sound.ts. They follow the same per-device sound setting
// and the user's quiet hours: with sound off a call still shows, silently.
import { inQuietHours, soundEnabled } from "@/lib/sound";

type Quiet = { start?: string; end?: string; timezone?: string } | null | undefined;
type AudioCtor = typeof AudioContext;

// Incoming: a two-tone ring every 3 s. Outgoing (ringback): one soft tone every 4 s.
const PATTERNS = {
  incoming: { every: 3000, tones: [[660, 0, 0.4], [880, 0.45, 0.4]] as const, gain: 0.2 },
  outgoing: { every: 4000, tones: [[440, 0, 1.2]] as const, gain: 0.08 },
};

let ctx: AudioContext | null = null;
let timer: number | null = null;

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

function beep(c: AudioContext, freq: number, offset: number, length: number, level: number) {
  const start = c.currentTime + offset;
  const osc = c.createOscillator();
  const gain = c.createGain();
  osc.connect(gain);
  gain.connect(c.destination);
  osc.type = "sine";
  osc.frequency.setValueAtTime(freq, start);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(level, start + 0.03);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + length);
  osc.start(start);
  osc.stop(start + length + 0.02);
}

/** Start looping a tone. Returns whether it plays (sound on, not quiet time, audio unlocked). */
export function startTone(kind: keyof typeof PATTERNS, quiet?: Quiet): boolean {
  stopTone();
  if (!soundEnabled() || inQuietHours(quiet)) return false;
  const c = context();
  if (!c) return false;
  const pattern = PATTERNS[kind];
  const play = () => {
    if (c.state !== "running") return;
    pattern.tones.forEach(([freq, offset, length]) => beep(c, freq, offset, length, pattern.gain));
  };
  play();
  timer = window.setInterval(play, pattern.every);
  return true;
}

export function stopTone(): void {
  if (timer !== null) window.clearInterval(timer);
  timer = null;
}

export function toneActive(): boolean {
  return timer !== null;
}
