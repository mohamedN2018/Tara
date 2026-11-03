import { afterEach, describe, expect, it, vi } from "vitest";

import { gridLayout } from "@/lib/mediaGrid";
import {
  clampIndex,
  formatView,
  keyToDelta,
  parseView,
  stepIndex,
  swipeToDelta,
} from "@/lib/mediaViewer";
import { api } from "@/lib/api";
import { IMAGE_ACCEPT, isHeic, uploadMime } from "@/lib/heic";
import { mediaService } from "@/services/media";

describe("gridLayout", () => {
  it("has no tiles without photos", () => {
    expect(gridLayout(0)).toEqual({ kind: "none", container: "", tiles: [] });
  });

  it("shows one wide photo", () => {
    const g = gridLayout(1);
    expect(g.kind).toBe("single");
    expect(g.tiles.map((t) => t.index)).toEqual([0]);
  });

  it("shows two squares", () => {
    const g = gridLayout(2);
    expect(g.kind).toBe("pair");
    expect(g.container).toContain("grid-cols-2");
    expect(g.tiles.every((t) => t.cell.includes("aspect-square"))).toBe(true);
  });

  it("shows a tall first photo beside two for three", () => {
    const g = gridLayout(3);
    expect(g.kind).toBe("triple");
    expect(g.tiles[0].cell).toContain("row-span-2");
    expect(g.tiles.map((t) => t.index)).toEqual([0, 1, 2]);
    expect(g.tiles.every((t) => t.overflow === 0)).toBe(true);
  });

  it("shows four tiles and no +N for exactly four", () => {
    const g = gridLayout(4);
    expect(g.kind).toBe("quad");
    expect(g.tiles.map((t) => t.overflow)).toEqual([0, 0, 0, 0]);
  });

  it("puts +N for the hidden photos on the fourth tile", () => {
    const g = gridLayout(10);
    expect(g.tiles).toHaveLength(4);
    expect(g.tiles.map((t) => t.overflow)).toEqual([0, 0, 0, 6]);
    // The fourth tile still opens the fourth photo; the viewer shows the rest.
    expect(g.tiles[3].index).toBe(3);
  });
});

describe("?view= parameter", () => {
  it("round-trips post id and index", () => {
    const id = "0190f3c2-7a1b-7cde-8f00-112233445566";
    expect(parseView(formatView(id, 3))).toEqual({ postId: id, index: 3 });
  });

  it("opens photo 0 when the index is missing or bad", () => {
    expect(parseView("abc")).toEqual({ postId: "abc", index: 0 });
    expect(parseView("abc:x")).toEqual({ postId: "abc", index: 0 });
    expect(parseView("abc:-1")).toEqual({ postId: "abc", index: 0 });
  });

  it("is closed for anything malformed", () => {
    expect(parseView(undefined)).toBeNull();
    expect(parseView("")).toBeNull();
    expect(parseView("<script>:1")).toBeNull();
    expect(parseView(["abc:2", "def:1"])).toEqual({ postId: "abc", index: 2 });
  });

  it("clamps a stale index into the post's photos", () => {
    expect(clampIndex(9, 3)).toBe(2);
    expect(clampIndex(-2, 3)).toBe(0);
    expect(clampIndex(1, 0)).toBe(0);
  });

  it("wraps when stepping past either end", () => {
    expect(stepIndex(2, 1, 3)).toBe(0);
    expect(stepIndex(0, -1, 3)).toBe(2);
    expect(stepIndex(1, 1, 3)).toBe(2);
  });
});

describe("viewer navigation follows the reading direction", () => {
  it("maps arrow keys in LTR", () => {
    expect(keyToDelta("ArrowRight", "ltr")).toBe(1);
    expect(keyToDelta("ArrowLeft", "ltr")).toBe(-1);
    expect(keyToDelta("Enter", "ltr")).toBe(0);
  });

  it("mirrors arrow keys in RTL", () => {
    expect(keyToDelta("ArrowLeft", "rtl")).toBe(1);
    expect(keyToDelta("ArrowRight", "rtl")).toBe(-1);
  });

  it("swipe left is next in LTR, swipe right is next in RTL", () => {
    expect(swipeToDelta(-80, "ltr")).toBe(1);
    expect(swipeToDelta(80, "ltr")).toBe(-1);
    expect(swipeToDelta(80, "rtl")).toBe(1);
    expect(swipeToDelta(-80, "rtl")).toBe(-1);
  });

  it("ignores short or mostly vertical swipes", () => {
    expect(swipeToDelta(20, "ltr")).toBe(0);
    expect(swipeToDelta(-60, "rtl", 120)).toBe(0);
  });
});

describe("HEIC upload", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("recognises HEIC by name or type", () => {
    expect(isHeic({ name: "IMG_0001.HEIC", type: "" })).toBe(true);
    expect(isHeic({ name: "photo", type: "image/heif" })).toBe(true);
    expect(isHeic({ name: "photo.jpg", type: "image/jpeg" })).toBe(false);
    expect(isHeic(null)).toBe(false);
    expect(IMAGE_ACCEPT).toContain(".heic");
    expect(IMAGE_ACCEPT).toContain(".heif");
  });

  it("keeps the real MIME and names HEIC when the browser reports none", () => {
    expect(uploadMime({ name: "IMG_0001.heic", type: "image/heic" })).toBe("image/heic");
    expect(uploadMime({ name: "IMG_0002.HEIF", type: "" })).toBe("image/heif");
    expect(uploadMime({ name: "IMG_0003.heic", type: "" })).toBe("image/heic");
    expect(uploadMime({ name: "a.jpg", type: "image/jpeg" })).toBe("image/jpeg");
    expect(uploadMime({ name: "blob", type: "" })).toBe("application/octet-stream");
  });

  it("uploads a HEIC photo unchanged, signed as image/heic", async () => {
    const post = vi.spyOn(api, "post").mockImplementation(async (url: string) =>
      url.endsWith("/sign/")
        ? { data: { data: { media_id: "m1", storage_key: "k", upload_url: "/__s3/x", method: "PUT", expires_in: 900 } } }
        : { data: { data: { id: "m1", kind: "image", status: "processing", url: null } } },
    );
    const put = vi.fn(async () => new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", put);
    const file = new File(["heic-bytes"], "IMG_0001.heic", { type: "" });

    const asset = await mediaService.upload(file, "image");

    expect(asset.id).toBe("m1");
    expect(post).toHaveBeenCalledWith("/media/uploads/sign/", expect.objectContaining({ kind: "image", mime: "image/heic" }));
    expect(put).toHaveBeenCalledWith("/__s3/x", expect.objectContaining({ body: file, headers: { "Content-Type": "image/heic" } }));
  });
});
