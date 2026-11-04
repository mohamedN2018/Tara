// Scroll to the element a URL hash names (/settings/security#phone), waiting
// for it to render: many settings cards appear only after their own fetch, so
// the router's scrollBehavior and a nextTick both run before the anchor exists.
// Once it is there, cards above it that finish loading would push it away, so
// for `settle` ms every DOM change scrolls it back into place. The wait ends
// when that window closes, after `timeout` without the anchor, or as soon as
// the person scrolls, touches or presses a key: a late jump must never yank the
// page away from where they went themselves.

const USER_EVENTS = ["wheel", "touchmove", "keydown", "pointerdown"] as const;

export function scrollToHashWhenReady(
  hash: string,
  { timeout = 5000, settle = 1500, root }: { timeout?: number; settle?: number; root?: Node } = {},
): () => void {
  if (!hash || hash === "#") return () => {};
  const find = (): Element | null => document.querySelector(hash);
  let first: Element | null;
  try {
    first = find();
  } catch {
    return () => {}; // not a valid selector (e.g. "#1x")
  }

  let done = false;
  let found = false;
  let timer = 0;
  const observer = new MutationObserver(() => {
    const el = find();
    if (el) align(el);
  });
  function align(el: Element) {
    if (!found) {
      found = true;
      window.clearTimeout(timer);
      timer = window.setTimeout(stop, settle);
    }
    el.scrollIntoView({ block: "start" });
  }
  function stop() {
    if (done) return;
    done = true;
    observer.disconnect();
    window.clearTimeout(timer);
    for (const name of USER_EVENTS) window.removeEventListener(name, stop);
  }

  timer = window.setTimeout(stop, timeout);
  observer.observe(root ?? document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["id"] });
  for (const name of USER_EVENTS) window.addEventListener(name, stop, { passive: true });
  if (first) align(first);
  return stop;
}
