import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { scrollToHashWhenReady } from "@/lib/hashScroll";

// /settings/security#phone: the phone card renders only after its fetch, so the
// scroll has to wait for the anchor instead of giving up on the first look.
describe("scrollToHashWhenReady", () => {
  const scrolled: string[] = [];
  const stops: (() => void)[] = [];
  const scroll = (...args: Parameters<typeof scrollToHashWhenReady>) => {
    const stop = scrollToHashWhenReady(...args);
    stops.push(stop);
    return stop;
  };

  beforeEach(() => {
    vi.useFakeTimers();
    scrolled.length = 0;
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this.id);
    };
  });
  afterEach(() => {
    stops.splice(0).forEach((stop) => stop());
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  const flush = () => new Promise<void>((resolve) => queueMicrotask(resolve));

  function add(id = "") {
    const el = document.createElement("li");
    el.id = id;
    document.body.appendChild(el);
  }

  it("scrolls at once when the anchor is already there", () => {
    add("phone");
    scroll("#phone");
    expect(scrolled).toEqual(["phone"]);
  });

  it("waits for an anchor rendered after an async load", async () => {
    scroll("#phone");
    expect(scrolled).toEqual([]);
    add(); // something else renders first
    await flush();
    expect(scrolled).toEqual([]);
    add("phone");
    await flush();
    expect(scrolled).toEqual(["phone"]);
  });

  it("keeps the anchor in place while cards above it load, then lets go", async () => {
    scroll("#phone", { settle: 1000 });
    add("phone");
    await flush();
    add(); // a card above finished loading and pushed it down
    await flush();
    expect(scrolled).toEqual(["phone", "phone"]);
    vi.advanceTimersByTime(1001);
    add();
    await flush();
    expect(scrolled).toEqual(["phone", "phone"]);
  });

  it("gives up after the timeout, when cancelled, or once the person scrolls", async () => {
    scroll("#late", { timeout: 1000 });
    vi.advanceTimersByTime(1001);
    add("late");
    await flush();

    const cancel = scroll("#cancelled");
    cancel();
    add("cancelled");
    await flush();

    scroll("#moved");
    window.dispatchEvent(new Event("wheel"));
    add("moved");
    await flush();

    expect(scrolled).toEqual([]);
  });

  it("ignores a hash that is not a selector", () => {
    expect(() => scroll("#1x")).not.toThrow();
    expect(scrolled).toEqual([]);
  });
});
