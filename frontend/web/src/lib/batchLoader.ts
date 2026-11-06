// Coalesce many single-id lookups into one batched request per tick.
//
// A page renders dozens of images, avatars and video tiles at once; asking
// media for each one on its own (about 200 calls for one home load) ran into
// the per-account rate limit and left tiles blank. Every `load(id)` made in the
// same short window goes out in one request of at most `max` ids, the same id
// asked twice shares one answer, and a 429 is retried with backoff instead of
// becoming an empty tile.

export interface BatchLoaderOptions<T> {
  /** One request for these ids; the answer omits the ones the viewer may not see. */
  fetch: (ids: string[]) => Promise<T[]>;
  /** The id an answer belongs to. */
  idOf: (item: T) => string;
  /** Ids per request (the server's cap). */
  max?: number;
  /** How long to gather lookups before sending, in ms (0: the rest of this tick). A
   * function is read at each batch, so a server setting (`delivery.media_resolve_window_ms`)
   * that arrives later applies to the next batch. */
  windowMs?: number | (() => number);
  /** Retries of a rate-limited (429) or unreachable request before giving up. */
  retries?: number;
  /** First backoff in ms; doubles each retry unless the server sends Retry-After. */
  backoffMs?: number;
  /** A label for the one console warning a failing batch logs. */
  label?: string;
  /** Test seam for the backoff wait. */
  sleep?: (ms: number) => Promise<void>;
}

interface HttpError {
  response?: { status?: number; headers?: Record<string, unknown> };
}

const statusOf = (err: unknown): number | undefined => (err as HttpError)?.response?.status;

/** Worth retrying: rate-limited, a gateway hiccup, or no answer at all. */
export function retryable(err: unknown): boolean {
  const status = statusOf(err);
  return status === undefined || status === 429 || status === 502 || status === 503 || status === 504;
}

/** The server's Retry-After (seconds) in ms, capped; null when absent or unreadable. */
export function retryAfterMs(err: unknown, capMs = 10_000): number | null {
  const raw = (err as HttpError)?.response?.headers?.["retry-after"];
  const seconds = Number(raw);
  if (raw === undefined || raw === null || raw === "" || !Number.isFinite(seconds) || seconds < 0) return null;
  return Math.min(seconds * 1000, capMs);
}

export function createBatchLoader<T>(options: BatchLoaderOptions<T>) {
  const {
    fetch,
    idOf,
    max = 100,
    windowMs = 0,
    retries = 4,
    backoffMs = 400,
    label = "batch",
    sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)),
  } = options;

  const windowOf = (): number => {
    const ms = typeof windowMs === "function" ? windowMs() : windowMs;
    return Number.isFinite(ms) && ms > 0 ? ms : 0;
  };

  type Waiter = { resolve: (v: T | null) => void; reject: (e: unknown) => void };
  const queued = new Map<string, Waiter[]>();
  const inflight = new Map<string, Promise<T | null>>();
  let timer: ReturnType<typeof setTimeout> | null = null;
  let warned = false;

  async function request(ids: string[]): Promise<T[]> {
    for (let attempt = 0; ; attempt++) {
      try {
        return await fetch(ids);
      } catch (err) {
        if (attempt >= retries || !retryable(err)) throw err;
        await sleep(retryAfterMs(err) ?? backoffMs * 2 ** attempt);
      }
    }
  }

  async function send(ids: string[], waiters: Map<string, Waiter[]>) {
    try {
      const found = new Map((await request(ids)).map((item) => [idOf(item), item]));
      for (const id of ids) for (const w of waiters.get(id) ?? []) w.resolve(found.get(id) ?? null);
    } catch (err) {
      if (!warned) {
        warned = true;
        console.warn(`[${label}] lookup failed (status ${statusOf(err) ?? "none"}); affected media stay hidden`, err);
      }
      for (const id of ids) for (const w of waiters.get(id) ?? []) w.reject(err);
    } finally {
      for (const id of ids) inflight.delete(id);
    }
  }

  function flush() {
    timer = null;
    const batch = new Map(queued);
    queued.clear();
    const ids = [...batch.keys()];
    for (let i = 0; i < ids.length; i += max) void send(ids.slice(i, i + max), batch);
  }

  /** The answer for `id`: null when the server left it out (unknown or not visible). */
  function load(id: string): Promise<T | null> {
    const pending = inflight.get(id);
    if (pending) return pending;
    const promise = new Promise<T | null>((resolve, reject) => {
      const list = queued.get(id) ?? [];
      list.push({ resolve, reject });
      queued.set(id, list);
    });
    inflight.set(id, promise);
    if (!timer) timer = setTimeout(flush, windowOf());
    return promise;
  }

  return { load };
}
