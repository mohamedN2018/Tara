// Video watch signals (Tara Intelligence WP 2.8): start, progress, complete,
// rewatch, skip and reel_view, from what the <video> element really played.
//
// Watch time is media time actually advanced by playback: a seek, a stall or a
// tab in the background adds nothing (only small forward steps between two
// `timeupdate`s count), so the client never claims time it did not play. The
// server clamps it again (duration x rewatch cap, wall-clock check).
import { type SignalSurface, track } from "./signals";

export const WATCH_RULES = {
  /** The largest step between two timeupdates that still counts as playback (s). */
  maxTickSeconds: 1.5,
  /** A progress event every 5 s of watch time (the tracker also caps it per 5 s of wall time). */
  progressEveryMs: 5_000,
  /** Complete: at least 90% of the duration watched in one play. */
  completeRatio: 0.9,
  /** Skip: left a play before min(2 s, 20% of the duration). */
  skipMaxMs: 2_000,
  skipRatio: 0.2,
  /** A reel counts as viewed after 1 s of play (post's MIN_VIEW_WATCH_MS). */
  reelViewMs: 1_000,
  /** A loop restart: from the last second back into the first one. */
  loopEdgeSeconds: 1,
} as const;

export interface WatchOptions {
  /** `video:<post id>` or `reel:<post id>`. */
  item: string;
  surface: SignalSurface;
  /** Called once per player when a reel has played for 1 s, with the watch time. */
  onReelView?: (watchMs: number) => void;
}

/** One player's watch state. Feed it the element's events; it emits the signals. */
export class WatchSession {
  private playIndex = 0;
  private watched = 0;
  private lastTime: number | null = null;
  private inPlay = false;
  private completed = false;
  private anyCompleted = false;
  private skipSent = false;
  private progressAt = 0;
  private reelViewed = false;

  constructor(private readonly opts: WatchOptions) {}

  get watchMs(): number {
    return Math.round(this.watched);
  }

  get play(): number {
    return this.playIndex;
  }

  private emit(t: Parameters<typeof track>[0]["t"], extra: Record<string, number> = {}) {
    track({ t, item: this.opts.item, surface: this.opts.surface, ...extra });
  }

  private beginPlay() {
    this.playIndex += 1;
    this.inPlay = true;
    this.watched = 0;
    this.completed = false;
    this.skipSent = false;
    this.progressAt = 0;
    this.emit("video_start", { play_index: this.playIndex });
    if (this.playIndex >= 2 && this.anyCompleted) this.emit("video_rewatch", { play_index: this.playIndex });
  }

  /** The element started (or resumed) playing. */
  playing(currentTime: number) {
    if (!this.inPlay) this.beginPlay();
    this.lastTime = currentTime;
  }

  /** A `timeupdate`: count the step if it is playback, not a seek. */
  time(currentTime: number, durationSeconds: number) {
    if (!this.inPlay) return;
    const last = this.lastTime;
    this.lastTime = currentTime;
    if (last === null) return;
    const step = currentTime - last;
    if (step < 0) {
      // A loop: the end played, the start comes round again.
      if (durationSeconds > 0 && last >= durationSeconds - WATCH_RULES.loopEdgeSeconds && currentTime < WATCH_RULES.loopEdgeSeconds) {
        this.ended(durationSeconds);
        this.beginPlay();
        this.lastTime = currentTime;
      }
      return;
    }
    if (step === 0 || step > WATCH_RULES.maxTickSeconds) return;
    this.watched += step * 1000;
    this.check(currentTime, durationSeconds);
  }

  private check(currentTime: number, durationSeconds: number) {
    const durationMs = durationSeconds > 0 && Number.isFinite(durationSeconds) ? durationSeconds * 1000 : 0;
    if (this.watched - this.progressAt >= WATCH_RULES.progressEveryMs) {
      this.progressAt = this.watched;
      this.emit("video_progress", { watch_ms: this.watchMs, pos_ms: Math.round(currentTime * 1000) });
    }
    if (!this.completed && durationMs && this.watched >= WATCH_RULES.completeRatio * durationMs) {
      this.completed = true;
      this.anyCompleted = true;
      this.emit("video_complete", { watch_ms: this.watchMs });
    }
    if (this.opts.onReelView && !this.reelViewed && this.watched >= WATCH_RULES.reelViewMs) {
      this.reelViewed = true;
      this.emit("reel_view", { watch_ms: this.watchMs });
      this.opts.onReelView(this.watchMs);
    }
  }

  /** The play reached its end (`ended`, or a loop restart). */
  ended(durationSeconds: number) {
    if (!this.inPlay) return;
    this.lastTime = null;
    this.inPlay = false;
    if (!this.completed && durationSeconds > 0 && this.watched >= WATCH_RULES.completeRatio * durationSeconds * 1000) {
      this.completed = true;
      this.anyCompleted = true;
      this.emit("video_complete", { watch_ms: this.watchMs });
    }
  }

  /** Paused, scrolled away or unmounted: an early exit is a skip (a weak signal). */
  left(durationSeconds: number) {
    this.lastTime = null;
    if (!this.inPlay || this.completed || this.skipSent) return;
    const durationMs = durationSeconds > 0 && Number.isFinite(durationSeconds) ? durationSeconds * 1000 : Infinity;
    const limit = Math.min(WATCH_RULES.skipMaxMs, WATCH_RULES.skipRatio * durationMs);
    if (this.watched < limit) {
      this.skipSent = true;
      this.emit("video_skip", { watch_ms: this.watchMs });
    }
  }

  /** A seek: the next step starts from the new position. */
  seeked(currentTime: number) {
    this.lastTime = this.inPlay ? currentTime : null;
  }
}

/** Wire a session to a <video> element. Returns the unbind function (call it on unmount). */
export function bindWatchSignals(video: HTMLVideoElement, opts: WatchOptions): () => void {
  const session = new WatchSession(opts);
  const duration = () => (Number.isFinite(video.duration) ? video.duration : 0);
  const on: Record<string, () => void> = {
    playing: () => session.playing(video.currentTime),
    timeupdate: () => session.time(video.currentTime, duration()),
    pause: () => session.left(duration()),
    ended: () => session.ended(duration()),
    seeked: () => session.seeked(video.currentTime),
  };
  for (const [name, fn] of Object.entries(on)) video.addEventListener(name, fn);
  return () => {
    session.left(duration());
    for (const [name, fn] of Object.entries(on)) video.removeEventListener(name, fn);
  };
}
