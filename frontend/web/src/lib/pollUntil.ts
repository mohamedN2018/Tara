/**
 * Call `check` every `intervalMs` until it returns true, `timeoutMs` passes, or
 * the returned `stop()` is called. Failed checks are retried (a network blip
 * must not end the wait). Resolves true when `check` succeeded.
 */
export function pollUntil(
  check: () => Promise<boolean>,
  { intervalMs, timeoutMs }: { intervalMs: number; timeoutMs: number },
): { done: Promise<boolean>; stop: () => void } {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  let finish: (ok: boolean) => void = () => {};
  const done = new Promise<boolean>((resolve) => {
    finish = resolve;
  });
  const deadline = Date.now() + timeoutMs;

  const tick = async () => {
    if (stopped) return;
    let ok = false;
    try {
      ok = await check();
    } catch {
      ok = false;
    }
    if (stopped) return;
    if (ok) {
      stopped = true;
      finish(true);
    } else if (Date.now() + intervalMs > deadline) {
      stopped = true;
      finish(false);
    } else {
      timer = setTimeout(tick, intervalMs);
    }
  };
  timer = setTimeout(tick, intervalMs);

  return {
    done,
    stop: () => {
      stopped = true;
      if (timer !== undefined) clearTimeout(timer);
      finish(false);
    },
  };
}
