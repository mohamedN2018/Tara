import { describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref } from "vue";

import { useMediaList } from "@/lib/useMediaList";
import { mediaService } from "@/services/media";

const flush = async () => {
  for (let i = 0; i < 20; i++) await nextTick();
};

describe("useMediaList", () => {
  it("resolves once per id change and never re-runs on its own writes", async () => {
    // A cached URL resolves at once: the old effect re-ran on its own write in
    // an endless microtask loop that froze any page with a photo post.
    const resolve = vi.spyOn(mediaService, "resolveUrl").mockImplementation(async (id) => `/u/${id}`);
    const ids = ref(["a", "b"]);
    const scope = effectScope();
    const urls = scope.run(() => useMediaList(() => ids.value))!;

    await flush();
    expect(urls.value).toEqual(["/u/a", "/u/b"]);
    expect(resolve).toHaveBeenCalledTimes(2);

    ids.value = ["c"];
    await flush();
    expect(urls.value).toEqual(["/u/c"]);
    expect(resolve).toHaveBeenCalledTimes(3);

    scope.stop();
    resolve.mockRestore();
  });
});
