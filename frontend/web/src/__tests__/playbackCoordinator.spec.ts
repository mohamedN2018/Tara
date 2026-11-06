// WP 4c.6-B3 (08 §7.9): the `muted_single` policy.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SAFE_DEFAULTS, type VideoPolicy } from "@/lib/delivery";
import {
  autoplayAllowed,
  claim,
  type CoordinatedPlayer,
  currentPlayer,
  noteUnmute,
  register,
  report,
  resetCoordinator,
  userPaused,
} from "@/lib/playbackCoordinator";

const policy: VideoPolicy = { ...SAFE_DEFAULTS.home.video };

function player(p: VideoPolicy = policy) {
  const calls: string[] = [];
  const pl: CoordinatedPlayer & { calls: string[] } = {
    ratio: 0,
    calls,
    policy: () => p,
    autoplay: vi.fn(async (muted: boolean) => {
      calls.push(muted ? "play:muted" : "play:sound");
      return true;
    }),
    pause: vi.fn(() => calls.push("pause")),
  };
  register(pl);
  return pl;
}

beforeEach(() => {
  resetCoordinator();
  vi.useFakeTimers();
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
});
afterEach(() => {
  resetCoordinator();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("muted_single", () => {
  it("autoplays, muted, the most visible player once it has been ≥ 60% visible for 300 ms", async () => {
    const a = player();
    const b = player();
    report(a, 0.7);
    report(b, 0.95);
    await vi.advanceTimersByTimeAsync(299);
    expect(a.autoplay).not.toHaveBeenCalled();
    expect(b.autoplay).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(b.calls).toEqual(["play:muted"]);
    expect(a.autoplay).not.toHaveBeenCalled();
    expect(currentPlayer()).toBe(b);
  });

  it("keeps at most one playing: a more visible one takes over, the other pauses", async () => {
    const a = player();
    const b = player();
    report(a, 0.8);
    await vi.advanceTimersByTimeAsync(300);
    expect(currentPlayer()).toBe(a);
    report(a, 0.5);
    report(b, 1);
    await vi.advanceTimersByTimeAsync(300);
    expect(a.calls).toEqual(["play:muted", "pause"]);
    expect(currentPlayer()).toBe(b);
  });

  it("pauses below 25% visible", async () => {
    const a = player();
    report(a, 0.9);
    await vi.advanceTimersByTimeAsync(300);
    report(a, 0.2);
    expect(a.calls).toEqual(["play:muted", "pause"]);
    expect(currentPlayer()).toBeNull();
  });

  it("does not restart a video the viewer paused, and a viewer's play pauses the others", async () => {
    const a = player();
    const b = player();
    report(a, 0.9);
    await vi.advanceTimersByTimeAsync(300);
    userPaused(a);
    report(a, 0.95);
    await vi.advanceTimersByTimeAsync(1000);
    expect(a.calls).toEqual(["play:muted"]);
    claim(b);
    expect(a.pause).toHaveBeenCalled();
    expect(currentPlayer()).toBe(b);
  });

  it("an unmute applies to the next autoplayed video only", async () => {
    const a = player();
    const b = player();
    const c = player();
    noteUnmute();
    report(a, 0.9);
    await vi.advanceTimersByTimeAsync(300);
    report(a, 0);
    report(b, 0.9);
    await vi.advanceTimersByTimeAsync(300);
    report(b, 0);
    report(c, 0.9);
    await vi.advanceTimersByTimeAsync(300);
    expect(a.calls[0]).toBe("play:sound");
    expect(b.calls[0]).toBe("play:muted");
    expect(c.calls[0]).toBe("play:muted");
  });
});

describe("no autoplay", () => {
  it("when the surface says click", async () => {
    const a = player({ ...policy, autoplay: "click" });
    report(a, 1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(a.autoplay).not.toHaveBeenCalled();
  });

  it("when the browser asks to save data (respect_save_data)", () => {
    vi.stubGlobal("navigator", { connection: { saveData: true } });
    expect(autoplayAllowed(policy)).toBe(false);
    expect(autoplayAllowed({ ...policy, respect_save_data: false })).toBe(true);
  });

  it("when the viewer prefers reduced motion (respect_reduced_motion)", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce") }));
    expect(autoplayAllowed(policy)).toBe(false);
    expect(autoplayAllowed({ ...policy, respect_reduced_motion: false })).toBe(true);
  });
});

describe("VideoPlayer loading (08 §7.9)", () => {
  it("asks for playback and the poster only once near the viewport, and gives up its <video> far away", async () => {
    vi.useRealTimers();
    const { createApp, h } = await import("vue");
    const { i18n } = await import("@/i18n");
    const { videoService } = await import("@/services/video");
    const VideoPlayer = (await import("@/components/media/VideoPlayer.vue")).default;
    const { FakeIO, flush } = await import("./deliveryHarness");
    FakeIO.all = [];
    vi.stubGlobal("IntersectionObserver", FakeIO);
    const playback = vi.spyOn(videoService, "playback").mockResolvedValue({
      id: "v1",
      status: "ready",
      failure_code: null,
      duration_ms: 1000,
      width: 1280,
      height: 720,
      hls_url: "/api/v1/media/v1/hls/master.m3u8",
      mp4_url: null,
      poster_url: "https://cdn.example/poster.jpg",
      poster_480_url: "https://cdn.example/poster_480.jpg",
      expires_in: 600,
    } as never);
    const host = document.createElement("div");
    document.body.appendChild(host);
    const app = createApp({ render: () => h(VideoPlayer, { mediaId: "v1" }) });
    app.use(i18n).mount(host);
    await flush();
    expect(playback).not.toHaveBeenCalled();
    expect(host.querySelector("video")).toBeNull();
    const vh = window.innerHeight;
    const near = FakeIO.all.find((o) => o.options.rootMargin === `${Math.round(1 * vh)}px 0px`)!;
    const far = FakeIO.all.find((o) => o.options.rootMargin === `${Math.round(3 * vh)}px 0px`)!;
    near.fire(true);
    await flush();
    expect(playback).toHaveBeenCalledTimes(1);
    expect(host.querySelector("video")?.getAttribute("poster")).toBe("https://cdn.example/poster_480.jpg");
    expect(host.querySelector("video")?.getAttribute("preload")).toBe("none");
    far.fire(false);
    await flush();
    expect(host.querySelector("video")).toBeNull();
    expect(host.querySelector("img[data-poster]")?.getAttribute("src")).toBe("https://cdn.example/poster_480.jpg");
    app.unmount();
    host.remove();
  });
});
