import { onBeforeUnmount, onMounted } from "vue";

/**
 * Call `tick` now and then every `intervalMs` while the page is visible. A
 * hidden tab stops polling; coming back polls at once and resumes the timer.
 * Returns a function that stops it for good.
 */
export function startVisiblePolling(tick: () => unknown, intervalMs: number, doc: Document = document): () => void {
  let timer: ReturnType<typeof setInterval> | null = null;
  let stopped = false;

  const run = () => {
    void Promise.resolve()
      .then(tick)
      .catch(() => {}); // the caller shows its own error state
  };
  const pause = () => {
    if (timer !== null) clearInterval(timer);
    timer = null;
  };
  const resume = () => {
    if (stopped || timer !== null) return;
    run();
    timer = setInterval(run, intervalMs);
  };
  const onVisibility = () => (doc.hidden ? pause() : resume());

  doc.addEventListener("visibilitychange", onVisibility);
  if (!doc.hidden) resume();

  return () => {
    stopped = true;
    pause();
    doc.removeEventListener("visibilitychange", onVisibility);
  };
}

/** Component form: polls while mounted and visible. */
export function useVisiblePolling(tick: () => unknown, intervalMs: number): void {
  let stop: (() => void) | null = null;
  onMounted(() => (stop = startVisiblePolling(tick, intervalMs)));
  onBeforeUnmount(() => stop?.());
}
