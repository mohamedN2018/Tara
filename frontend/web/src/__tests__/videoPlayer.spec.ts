import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, h } from "vue";

import VideoPlayer from "@/components/media/VideoPlayer.vue";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { apiUrl, isProcessing, videoMime } from "@/services/video";

// hls.js is lazy-loaded by the player; a fake records what it was asked to do.
const hlsState = vi.hoisted(() => ({
  instances: [] as Array<{
    config: { xhrSetup?: (xhr: XMLHttpRequest, url: string) => void };
    sources: string[];
    media: HTMLMediaElement | null;
    handlers: Record<string, (event: string, data: { fatal?: boolean; type?: string }) => void>;
    destroyed: boolean;
  }>,
  supported: true,
}));

vi.mock("hls.js", () => {
  class FakeHls {
    static Events = { ERROR: "hlsError" };
    static ErrorTypes = { NETWORK_ERROR: "networkError", MEDIA_ERROR: "mediaError" };
    static isSupported = () => hlsState.supported;
    record: (typeof hlsState.instances)[number];
    constructor(config: (typeof hlsState.instances)[number]["config"]) {
      this.record = { config, sources: [], media: null, handlers: {}, destroyed: false };
      hlsState.instances.push(this.record);
    }
    loadSource(url: string) {
      this.record.sources.push(url);
    }
    attachMedia(el: HTMLMediaElement) {
      this.record.media = el;
    }
    on(event: string, cb: (event: string, data: { fatal?: boolean; type?: string }) => void) {
      this.record.handlers[event] = cb;
    }
    recoverMediaError() {}
    destroy() {
      this.record.destroyed = true;
    }
  }
  return { default: FakeHls };
});

const MEDIA_ID = "01a1a55d-05d8-76fb-93a7-03b04162793a";

function playback(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      data: {
        id: MEDIA_ID,
        status: "ready",
        failure_code: null,
        duration_ms: 3000,
        width: 640,
        height: 360,
        hls_url: `media/${MEDIA_ID}/hls/master.m3u8?token=abc`,
        mp4_url: null,
        poster_url: "http://minio:9000/tara-media/videos/o/i/poster.jpg?X-Amz-Signature=1",
        expires_in: 3600,
        ...overrides,
      },
    },
  };
}

let app: App | null = null;
let host: HTMLElement | null = null;
const statuses: string[] = [];

async function flush() {
  for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0));
}

async function mount(props: Record<string, unknown> = {}) {
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({
    render: () => h(VideoPlayer, { mediaId: MEDIA_ID, pollMs: 5, onStatus: (s: string) => statuses.push(s), ...props }),
  });
  app.use(i18n);
  app.mount(host);
  await flush();
  return host;
}

const q = <T extends Element = HTMLElement>(sel: string) => host!.querySelector(sel) as T | null;

beforeEach(() => {
  hlsState.instances.length = 0;
  hlsState.supported = true;
  statuses.length = 0;
  i18n.global.locale.value = "ar";
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  });
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (this: HTMLMediaElement) {
    this.dispatchEvent(new Event("pause"));
  });
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
  i18n.global.locale.value = "ar";
});

describe("VideoPlayer", () => {
  it("shows the poster and loads hls.js only on the first play", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue(playback());
    await mount();
    expect(get).toHaveBeenCalledWith(`/media/${MEDIA_ID}/playback/`);
    expect(q("[data-testid=video-player]")?.dataset.state).toBe("ready");
    // The poster goes through the storage proxy in dev/e2e builds.
    expect(q<HTMLVideoElement>("video")?.getAttribute("poster")).toBe("/__s3/tara-media/videos/o/i/poster.jpg?X-Amz-Signature=1");
    expect(hlsState.instances).toHaveLength(0);

    q<HTMLButtonElement>("[data-testid=video-play]")!.click();
    await flush();
    expect(hlsState.instances).toHaveLength(1);
    const [hls] = hlsState.instances;
    expect(hls.sources[0]).toBe(new URL(`/api/v1/media/${MEDIA_ID}/hls/master.m3u8?token=abc`, window.location.href).toString());
    expect(hls.media).toBe(q("video"));
    expect(q("[data-testid=video-controls]")).not.toBeNull();
  });

  it("keeps the scrubber left to right in Arabic and seeks where it is dragged", async () => {
    vi.spyOn(api, "get").mockResolvedValue(playback());
    await mount();
    q<HTMLButtonElement>("[data-testid=video-play]")!.click();
    await flush();
    const controls = q("[data-testid=video-controls]")!;
    const scrubber = q<HTMLInputElement>("[data-testid=video-scrubber]")!;
    // The page is dir="rtl"; media time must not run backwards.
    expect(controls.getAttribute("dir")).toBe("ltr");
    expect(scrubber.getAttribute("dir")).toBe("ltr");
    expect(scrubber.getAttribute("aria-label")).toBe("موضع التشغيل");
    expect(scrubber.max).toBe("3");
    const video = q<HTMLVideoElement>("video")!;
    scrubber.value = "2";
    scrubber.dispatchEvent(new Event("input"));
    await flush();
    expect(video.currentTime).toBe(2);
    expect(q("[data-testid=video-time]")?.textContent).toBe("0:02 / 0:03");
    expect(q("[data-testid=video-time]")?.getAttribute("dir")).toBe("ltr");
    expect(scrubber.getAttribute("aria-valuetext")).toBe("0:02 من 0:03");
  });

  it("uses English labels in English", async () => {
    i18n.global.locale.value = "en";
    vi.spyOn(api, "get").mockResolvedValue(playback());
    await mount();
    expect(q("[data-testid=video-play]")?.getAttribute("aria-label")).toBe("Play");
  });

  it("polls while the owner's video is processing, then becomes playable", async () => {
    const get = vi
      .spyOn(api, "get")
      .mockResolvedValueOnce(playback({ status: "uploaded", hls_url: null, poster_url: null }))
      .mockResolvedValueOnce(playback({ status: "processing", hls_url: null, poster_url: null }))
      .mockResolvedValue(playback());
    await mount();
    expect(statuses[0]).toBe("uploaded");
    await new Promise((r) => setTimeout(r, 40));
    await flush();
    expect(get.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(statuses).toEqual(["uploaded", "processing", "ready"]);
    expect(q("[data-testid=video-player]")?.dataset.state).toBe("ready");
  });

  it("explains why a video failed", async () => {
    vi.spyOn(api, "get").mockResolvedValue(playback({ status: "failed", failure_code: "too_long", hls_url: null }));
    await mount();
    expect(q("[data-testid=video-player]")?.dataset.state).toBe("failed");
    expect(q("[data-testid=video-failure]")?.textContent).toBe("الفيديو أطول من الحد المسموح.");
  });

  it("falls back to a generic reason for an unknown failure code", async () => {
    i18n.global.locale.value = "en";
    vi.spyOn(api, "get").mockResolvedValue(playback({ status: "failed", failure_code: "weird", hls_url: null }));
    await mount();
    expect(q("[data-testid=video-failure]")?.textContent).toBe("Something went wrong while processing. Upload the video again.");
  });

  it("shows a hidden or removed video as unavailable", async () => {
    vi.spyOn(api, "get").mockRejectedValue({ response: { status: 404 } });
    await mount();
    expect(q("[data-testid=video-player]")?.dataset.state).toBe("unavailable");
    expect(q("video")?.getAttribute("poster")).toBeNull();
  });

  it("sends only storage URLs through the dev storage proxy", async () => {
    vi.spyOn(api, "get").mockResolvedValue(playback());
    await mount();
    q<HTMLButtonElement>("[data-testid=video-play]")!.click();
    await flush();
    const setup = hlsState.instances[0].config.xhrSetup!;
    const open = vi.fn();
    setup({ open } as unknown as XMLHttpRequest, "http://minio:9000/tara-media/videos/o/i/hls/360/seg_00000.ts?X-Amz-Expires=300");
    expect(open).toHaveBeenCalledWith("GET", "/__s3/tara-media/videos/o/i/hls/360/seg_00000.ts?X-Amz-Expires=300", true);
    open.mockClear();
    setup({ open } as unknown as XMLHttpRequest, new URL("/api/v1/media/x/hls/360.m3u8?token=t", window.location.href).toString());
    expect(open).not.toHaveBeenCalled();
  });

  it("fetches a fresh token once when the stream fails, and resumes", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue(playback());
    await mount();
    q<HTMLButtonElement>("[data-testid=video-play]")!.click();
    await flush();
    q<HTMLVideoElement>("video")!.currentTime = 1.5;
    hlsState.instances[0].handlers.hlsError("hlsError", { fatal: true, type: "networkError" });
    await flush();
    expect(get).toHaveBeenCalledTimes(2);
    expect(hlsState.instances).toHaveLength(2);
    expect(hlsState.instances[0].destroyed).toBe(true);
    expect(q<HTMLVideoElement>("video")!.currentTime).toBe(1.5);
    // A second failure gives up with a retry button instead of looping.
    hlsState.instances[1].handlers.hlsError("hlsError", { fatal: true, type: "networkError" });
    await flush();
    expect(q("[data-testid=video-player]")?.dataset.state).toBe("error");
  });

  it("refreshes again on every later expiry once playback resumed, but not in a tight loop", async () => {
    let now = 1_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    const get = vi.spyOn(api, "get").mockResolvedValue(playback());
    await mount();
    q<HTMLButtonElement>("[data-testid=video-play]")!.click();
    await flush();
    const video = q<HTMLVideoElement>("video")!;
    // Segment URLs expire every few minutes: each expiry gets a fresh playlist.
    for (let i = 0; i < 3; i++) {
      now += 200_000;
      video.currentTime = 10 + i;
      hlsState.instances[i].handlers.hlsError("hlsError", { fatal: true, type: "networkError" });
      await flush();
      expect(hlsState.instances).toHaveLength(i + 2);
      expect(video.currentTime).toBe(10 + i);
      expect(q("[data-testid=video-player]")?.dataset.state).toBe("ready");
      video.dispatchEvent(new Event("playing"));
    }
    expect(get).toHaveBeenCalledTimes(4);
    // Failing again right after a refresh that played is a loop, not an expiry.
    now += 1_000;
    hlsState.instances[3].handlers.hlsError("hlsError", { fatal: true, type: "networkError" });
    await flush();
    expect(q("[data-testid=video-player]")?.dataset.state).toBe("error");
    expect(get).toHaveBeenCalledTimes(4);
  });

  it("builds no hls.js instance when unmounted while hls.js is still downloading", async () => {
    vi.spyOn(api, "get").mockResolvedValue(playback());
    await mount();
    q<HTMLButtonElement>("[data-testid=video-play]")!.click();
    app!.unmount();
    app = null;
    await flush();
    expect(hlsState.instances).toHaveLength(0);
  });

  it("does not attach a refreshed stream after unmount", async () => {
    vi.spyOn(api, "get").mockResolvedValue(playback());
    await mount();
    q<HTMLButtonElement>("[data-testid=video-play]")!.click();
    await flush();
    hlsState.instances[0].handlers.hlsError("hlsError", { fatal: true, type: "networkError" });
    app!.unmount();
    app = null;
    await flush();
    expect(hlsState.instances).toHaveLength(1);
    expect(hlsState.instances[0].destroyed).toBe(true);
  });

  it("plays the MP4 fallback where neither hls.js nor native HLS works", async () => {
    hlsState.supported = false;
    vi.spyOn(api, "get").mockResolvedValue(playback({ mp4_url: "http://minio:9000/tara-media/videos/o/i/mp4/video.mp4?s=1" }));
    await mount();
    q<HTMLButtonElement>("[data-testid=video-play]")!.click();
    await flush();
    expect(q<HTMLVideoElement>("video")!.getAttribute("src")).toBe("/__s3/tara-media/videos/o/i/mp4/video.mp4?s=1");
  });
});

describe("video service helpers", () => {
  it("picks the MIME from the browser or the extension", () => {
    expect(videoMime({ name: "clip.mp4", type: "video/mp4" })).toBe("video/mp4");
    expect(videoMime({ name: "IMG_0001.MOV", type: "" })).toBe("video/quicktime");
    expect(videoMime({ name: "rec.webm", type: "application/octet-stream" })).toBe("video/webm");
    expect(videoMime({ name: "page.html", type: "text/html" })).toBeNull();
    expect(videoMime({ name: "x.avi", type: "" })).toBeNull();
  });

  it("resolves the playlist path against the API base", () => {
    expect(apiUrl("media/1/hls/master.m3u8?token=t")).toMatch(/\/api\/v1\/media\/1\/hls\/master\.m3u8\?token=t$/);
  });

  it("treats uploaded and processing as still processing", () => {
    expect(["uploading", "uploaded", "processing"].every(isProcessing)).toBe(true);
    expect(isProcessing("ready") || isProcessing("failed")).toBe(false);
  });
});
