// Feed video playback policy (Tara Intelligence 08 §7.9, WP 4c.6-B3).
//
// `muted_single`: at most one feed video plays at a time. The one that plays
// on its own is the most visible player that has been at least `min_visible`
// on screen for `min_visible_ms`, and it plays muted; a playing video pauses
// once less than `pause_below` of it is visible. No autoplay when the surface
// says `"click"`, when the browser asks to save data (`respect_save_data`), or
// when the viewer prefers reduced motion (`respect_reduced_motion`). A viewer's
// unmute carries over to the next video that autoplays in this session only.
// A video the viewer paused is not started again by the policy.
//
// The values are the surface's `delivery.video` block (the server's); players
// report their visible ratio and the coordinator decides.
import type { VideoPolicy } from "./delivery";

export interface CoordinatedPlayer {
  /** Visible ratio of the player (0..1), as the player last measured it. */
  ratio: number;
  policy: () => VideoPolicy;
  /** Start playing; `muted` as the policy says. Resolves false when the browser refused. */
  autoplay: (muted: boolean) => Promise<boolean>;
  pause: () => void;
  /** The viewer paused this one: the policy leaves it alone until they play it again. */
  userPaused?: boolean;
}

interface Entry {
  player: CoordinatedPlayer;
  since: number | null;
}

const entries = new Map<CoordinatedPlayer, Entry>();
let playing: CoordinatedPlayer | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;
let unmuteNext = false;

interface NetworkInformationLike {
  saveData?: boolean;
}

/** Whether the policy may start a video on its own on this device right now. */
export function autoplayAllowed(policy: VideoPolicy): boolean {
  if (policy.autoplay !== "muted_single") return false;
  if (policy.respect_save_data) {
    const conn = (globalThis.navigator as Navigator & { connection?: NetworkInformationLike } | undefined)?.connection;
    if (conn?.saveData) return false;
  }
  if (policy.respect_reduced_motion && typeof globalThis.matchMedia === "function") {
    try {
      if (globalThis.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
    } catch {
      // No media queries: no preference known.
    }
  }
  return true;
}

function schedule(ms: number) {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    timer = null;
    evaluate();
  }, Math.max(0, ms));
}

/** Pick the player that should be playing and make it so. */
export function evaluate(now = Date.now()) {
  if (playing) {
    const e = entries.get(playing);
    if (!e || playing.ratio < playing.policy().pause_below) {
      playing.pause();
      playing = null;
    }
  }
  let best: Entry | null = null;
  let wait = Infinity;
  for (const e of entries.values()) {
    const policy = e.player.policy();
    if (e.player.userPaused || !autoplayAllowed(policy)) continue;
    if (e.player.ratio < policy.min_visible) {
      e.since = null;
      continue;
    }
    if (e.since === null) e.since = now;
    const left = policy.min_visible_ms - (now - e.since);
    if (left > 0) {
      wait = Math.min(wait, left);
      continue;
    }
    if (!best || e.player.ratio > best.player.ratio) best = e;
  }
  if (best && best.player !== playing && (!playing || best.player.ratio > playing.ratio)) {
    const next = best.player;
    playing?.pause();
    playing = next;
    const muted = !unmuteNext;
    unmuteNext = false;
    void next.autoplay(muted).then((ok) => {
      if (!ok && playing === next) playing = null;
    });
  }
  if (Number.isFinite(wait)) schedule(wait);
}

/** Register a feed player; returns the unregister function. */
export function register(player: CoordinatedPlayer): () => void {
  entries.set(player, { player, since: null });
  return () => {
    entries.delete(player);
    if (playing === player) playing = null;
  };
}

/** A player's visible ratio changed. */
export function report(player: CoordinatedPlayer, ratio: number) {
  player.ratio = ratio;
  const e = entries.get(player);
  if (e && ratio < player.policy().min_visible) e.since = null;
  evaluate();
}

/** The viewer started this player themselves: every other one pauses. */
export function claim(player: CoordinatedPlayer) {
  player.userPaused = false;
  for (const e of entries.values()) if (e.player !== player) e.player.pause();
  playing = player;
}

/** The viewer paused it: the policy does not restart it. */
export function userPaused(player: CoordinatedPlayer) {
  player.userPaused = true;
  if (playing === player) playing = null;
}

/** The viewer unmuted a video: the next autoplay in this session starts with sound. */
export function noteUnmute() {
  unmuteNext = true;
}

/** Tests: forget every player and the carried-over unmute. */
export function resetCoordinator() {
  if (timer) clearTimeout(timer);
  timer = null;
  entries.clear();
  playing = null;
  unmuteNext = false;
}

/** Tests and tools: the player the policy has playing now. */
export function currentPlayer(): CoordinatedPlayer | null {
  return playing;
}
