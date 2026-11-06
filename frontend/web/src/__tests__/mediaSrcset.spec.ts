// WP 4c.5-B3, client (08 §7.8): variants in the URL cache, thumbs for grid
// tiles and avatars, a srcset only from variants the server sent (never a
// made-up width), image width/height, and a cache lifetime from urls_expire_at.
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, h } from "vue";

import UserAvatar from "@/components/common/UserAvatar.vue";
import MediaGrid from "@/components/post/MediaGrid.vue";
import StoryTrayCard from "@/components/stories/StoryTrayCard.vue";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { coverSizes } from "@/lib/useMediaList";
import { clearMediaCache, type MediaAsset, mediaService, srcsetOf, viaStorageProxy } from "@/services/media";

// Storage URLs as the page uses them (through the dev/e2e storage proxy when it is on).
const px = (u: string) => viaStorageProxy(u)!;

const asset = (id: string, extra: Partial<MediaAsset> = {}): MediaAsset => ({
  id,
  kind: "image",
  status: "ready",
  url: `https://cdn.example/${id}/orig.jpg`,
  width: 1600,
  height: 1200,
  urls_expire_at: Math.floor(Date.now() / 1000) + 3600,
  variants: [
    { kind: "thumb", url: `https://cdn.example/${id}/thumb.webp`, width: 320, height: 240 },
    { kind: "display_640", url: `https://cdn.example/${id}/640.webp`, width: 640, height: 480 },
    { kind: "display_1280", url: `https://cdn.example/${id}/1280.webp`, width: 1280, height: 960 },
  ],
  ...extra,
});

let resolveCalls: string[][];
let apps: App[] = [];
async function flush() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}
function mount(component: unknown, props: Record<string, unknown>) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const app = createApp({ render: () => h(component as never, props) });
  app.use(i18n).use(createPinia());
  app.mount(host);
  apps.push(app);
  return host;
}

beforeEach(() => {
  setActivePinia(createPinia());
  clearMediaCache();
  i18n.global.locale.value = "en";
  resolveCalls = [];
  vi.spyOn(api, "post").mockImplementation(async (url: string, body?: unknown) => {
    if (url !== "/media/resolve/") return { data: { data: [] } } as never;
    const ids = (body as { ids: string[] }).ids;
    resolveCalls.push(ids);
    return { data: { data: ids.map((id) => (id.startsWith("bare") ? asset(id, { variants: [], width: null, height: null }) : asset(id))) } } as never;
  });
});
afterEach(() => {
  apps.forEach((a) => a.unmount());
  apps = [];
  vi.useRealTimers();
});

describe("srcsetOf", () => {
  it("lists the variants with the widths the server sent, in order", () => {
    const view = srcsetOf({
      url: "o",
      width: 1600,
      height: 1200,
      variants: { thumb: { url: "t", width: 320 }, display_640: { url: "d6", width: 640 }, display_1280: { url: "d12", width: 1280 } },
    });
    expect(view).toEqual({ src: "d6", srcset: "t 320w, d6 640w, d12 1280w", width: 1600, height: 1200 });
  });

  it("leaves out a variant without a width, and makes no srcset from one candidate", () => {
    expect(srcsetOf({ url: "o", variants: { thumb: { url: "t", width: 320 }, display_640: { url: "d6" } } })).toEqual({ src: "d6" });
    expect(srcsetOf({ url: "o", variants: {} })).toEqual({ src: "o" });
  });
});

describe("media cache", () => {
  it("keeps variants, gives the thumb, and lives until urls_expire_at minus a margin", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-06T10:00:00Z"));
    vi.mocked(api.post).mockImplementation(async (_u, body) => {
      const ids = (body as { ids: string[] }).ids;
      resolveCalls.push(ids);
      return { data: { data: ids.map((id) => asset(id, { urls_expire_at: Math.floor(Date.now() / 1000) + 3600 })) } } as never;
    });
    expect(await mediaService.resolveThumb("m1")).toBe(px("https://cdn.example/m1/thumb.webp"));
    expect(mediaService.cachedThumb("m1")).toBe(px("https://cdn.example/m1/thumb.webp"));
    vi.setSystemTime(new Date("2026-11-06T10:50:00Z")); // past the old 10 min TTL, inside the hour
    expect(mediaService.cachedUrl("m1")).not.toBeNull();
    await mediaService.resolveUrl("m1");
    expect(resolveCalls).toHaveLength(1);
    vi.setSystemTime(new Date("2026-11-06T10:59:00Z")); // inside the safety margin: re-resolved
    expect(mediaService.cachedUrl("m1")).toBeNull();
    await mediaService.resolveUrl("m1");
    expect(resolveCalls).toHaveLength(2);
  });

  it("falls back to the display URL as thumb when an older asset has no variants", async () => {
    expect(await mediaService.resolveThumb("bare-1")).toBe(px("https://cdn.example/bare-1/orig.jpg"));
  });
});

describe("MediaGrid", () => {
  it("a single photo uses srcset, sizes, width and height (aspect ratio reserved)", async () => {
    const el = mount(MediaGrid, { mediaIds: ["m1"], authorName: "Sara", eager: true });
    await flush();
    const img = el.querySelector("img")!;
    expect(img.getAttribute("srcset")).toBe(
      `${px("https://cdn.example/m1/thumb.webp")} 320w, ${px("https://cdn.example/m1/640.webp")} 640w, ${px("https://cdn.example/m1/1280.webp")} 1280w`,
    );
    expect(img.getAttribute("sizes")).toBe("(max-width: 600px) 100vw, 600px");
    expect(img.getAttribute("width")).toBe("1600");
    expect(img.getAttribute("height")).toBe("1200");
    expect(img.style.aspectRatio).toBe("1600 / 1200");
    expect(img.getAttribute("loading")).toBe("eager");
    expect(img.getAttribute("fetchpriority")).toBe("high");
  });

  it("2+ photos load thumbnails, lazily; all of a page's ids go out in one resolve", async () => {
    const el = mount(MediaGrid, { mediaIds: ["a1", "a2", "a3"], authorName: "Sara" });
    await flush();
    const imgs = [...el.querySelectorAll("img")];
    expect(imgs.map((i) => i.getAttribute("src"))).toEqual(["a1", "a2", "a3"].map((id) => px(`https://cdn.example/${id}/thumb.webp`)));
    expect(imgs.every((i) => i.getAttribute("loading") === "lazy" && !i.hasAttribute("srcset"))).toBe(true);
    expect(resolveCalls).toEqual([["a1", "a2", "a3"]]);
  });

  it("an asset without sizes gets no width/height and no srcset (nothing invented)", async () => {
    const el = mount(MediaGrid, { mediaIds: ["bare-2"], authorName: "Sara" });
    await flush();
    const img = el.querySelector("img")!;
    expect(img.hasAttribute("srcset")).toBe(false);
    expect(img.hasAttribute("width")).toBe(false);
    expect(img.getAttribute("src")).toBe(px("https://cdn.example/bare-2/orig.jpg"));
  });
});

describe("UserAvatar", () => {
  it("always shows the thumbnail", async () => {
    const el = mount(UserAvatar, { name: "Sara", mediaId: "av1" });
    await flush();
    expect(el.querySelector("img")?.getAttribute("src")).toBe(px("https://cdn.example/av1/thumb.webp"));
  });
});

describe("story tiles (cover crop)", () => {
  it("sizes is the width the crop is drawn at: the box width, or the height times the aspect", () => {
    expect(coverSizes({ width: 1600, height: 1200 }, 128, 208)).toBe("278px");
    expect(coverSizes({ width: 800, height: 1600 }, 128, 208)).toBe("128px");
    expect(coverSizes({}, 128, 208)).toBe("208px");
  });

  it("a photo story card uses the display copies' srcset, never only the original", async () => {
    const group = {
      author_id: "a1",
      stories: [{ id: "s1", kind: "photo", media_id: "st1", background: null, text: "", created_at: new Date().toISOString(), seen: false }],
      all_seen: false,
    };
    const el = mount(StoryTrayCard, { group });
    await flush();
    const img = el.querySelector("img")!;
    expect(img.getAttribute("src")).toBe(px("https://cdn.example/st1/640.webp"));
    expect(img.getAttribute("srcset")).toContain(px("https://cdn.example/st1/1280.webp") + " 1280w");
    expect(img.getAttribute("sizes")).toBe("278px");
  });
});
