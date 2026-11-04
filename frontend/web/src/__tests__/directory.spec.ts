import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { profileService, type UserCard } from "@/services/profile";
import { useDirectoryStore } from "@/stores/directory";

const card = (id: string): UserCard => ({
  account_id: id,
  handle: `h_${id}`,
  display_name: `Name ${id}`,
  avatar_media_id: `avatar-${id}`,
});

async function settle() {
  await vi.advanceTimersByTimeAsync(100);
}

describe("directory store", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    setActivePinia(createPinia());
  });
  afterEach(() => vi.useRealTimers());

  it("collects reads into one debounced lookup", async () => {
    const lookup = vi.spyOn(profileService, "lookup").mockImplementation(async (ids) => ids.map(card));
    const directory = useDirectoryStore();
    directory.nameOf("a");
    directory.label("b");
    directory.avatarOf("c");
    directory.nameOf("a");
    expect(lookup).not.toHaveBeenCalled();
    await settle();
    expect(lookup).toHaveBeenCalledOnce();
    expect(lookup.mock.calls[0][0]).toEqual(["a", "b", "c"]);
    expect(directory.nameOf("a")).toBe("Name a");
    expect(directory.avatarOf("b")).toBe("avatar-b");
  });

  it("splits into batches of 100", async () => {
    const lookup = vi.spyOn(profileService, "lookup").mockImplementation(async (ids) => ids.map(card));
    const directory = useDirectoryStore();
    for (let i = 0; i < 250; i++) directory.nameOf(`u${i}`);
    await settle();
    expect(lookup.mock.calls.map((c) => c[0].length)).toEqual([100, 100, 50]);
  });

  it("does not ask twice for a known or in-flight id", async () => {
    let release: (cards: UserCard[]) => void = () => {};
    const lookup = vi
      .spyOn(profileService, "lookup")
      .mockImplementation(() => new Promise((resolve) => (release = resolve)));
    const directory = useDirectoryStore();
    directory.nameOf("a");
    await settle();
    directory.nameOf("a");
    await settle();
    expect(lookup).toHaveBeenCalledOnce();
    release([card("a")]);
    await settle();
    directory.nameOf("a");
    await settle();
    expect(lookup).toHaveBeenCalledOnce();
  });

  it("shows a placeholder, then a neutral label for users the server omits, never the id", async () => {
    vi.spyOn(profileService, "lookup").mockResolvedValue([]);
    const directory = useDirectoryStore();
    const id = "01a19ed4-9364-7abf-828d-aa6ae845af83";
    expect(directory.label(id)).toBe("…");
    expect(directory.pending(id)).toBe(true);
    await settle();
    // A miss is retried (a brand-new account's profile lags sign-up): still "…".
    expect(directory.label(id)).toBe("…");
    await vi.advanceTimersByTimeAsync(10_000);
    expect(directory.pending(id)).toBe(false);
    expect(directory.label(id)).not.toContain(id.slice(0, 8));
    expect(directory.label(id)).not.toBe("…");
  });

  it("retries an omitted id a few times, then doesn't re-request it", async () => {
    const lookup = vi.spyOn(profileService, "lookup").mockResolvedValue([]);
    const directory = useDirectoryStore();
    directory.nameOf("blocked");
    await vi.advanceTimersByTimeAsync(10_000);
    // Three tries in all (the first and two retries), then never again.
    expect(lookup).toHaveBeenCalledTimes(3);
    directory.nameOf("blocked");
    await vi.advanceTimersByTimeAsync(10_000);
    expect(lookup).toHaveBeenCalledTimes(3);
  });

  it("backs off after a failed lookup, then tries again", async () => {
    const lookup = vi.spyOn(profileService, "lookup").mockRejectedValueOnce(new Error("down"));
    lookup.mockImplementation(async (ids) => ids.map(card));
    const directory = useDirectoryStore();
    directory.nameOf("a");
    await settle();
    expect(lookup).toHaveBeenCalledTimes(1);
    directory.nameOf("a");
    await settle();
    expect(lookup).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    directory.nameOf("a");
    await settle();
    expect(lookup).toHaveBeenCalledTimes(2);
    expect(directory.nameOf("a")).toBe("Name a");
  });

  it("persists entries and restores them without a lookup", async () => {
    vi.spyOn(profileService, "lookup").mockImplementation(async (ids) => ids.map(card));
    useDirectoryStore().nameOf("a");
    await settle();
    await vi.advanceTimersByTimeAsync(600);

    setActivePinia(createPinia());
    const lookup = vi.spyOn(profileService, "lookup").mockClear();
    expect(useDirectoryStore().nameOf("a")).toBe("Name a");
    await settle();
    expect(lookup).not.toHaveBeenCalled();
  });

  it("drops the legacy cache, which could hold names spoofed through the URL", () => {
    localStorage.setItem("tara.directory", JSON.stringify({ a: { name: "Spoofed" } }));
    vi.spyOn(profileService, "lookup").mockResolvedValue([]);
    expect(useDirectoryStore().nameOf("a")).toBeUndefined();
    expect(localStorage.getItem("tara.directory")).toBeNull();
  });

  it("clear forgets everything, in memory and on disk, and ignores late responses", async () => {
    let release: (cards: UserCard[]) => void = () => {};
    vi.spyOn(profileService, "lookup").mockImplementation(
      () => new Promise((resolve) => (release = resolve)),
    );
    const directory = useDirectoryStore();
    directory.remember("a", "Alice");
    await vi.advanceTimersByTimeAsync(600);
    expect(localStorage.getItem("tara.directory.v2")).toContain("Alice");
    directory.nameOf("b");
    await settle();

    directory.clear();
    release([card("b")]);
    await settle();
    expect(directory.entries).toEqual({});
    expect(localStorage.getItem("tara.directory.v2")).toBeNull();
  });
});
