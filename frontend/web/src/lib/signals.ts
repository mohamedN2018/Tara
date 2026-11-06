// Tara Intelligence web tracker (WP 2.8): the client-only signals the server
// cannot observe (impressions, opens, video watch time, reel views, profile
// visits), batched to POST /feed/signals/ (docs/intelligence/02 §12.2, 03 §4.4).
//
// Rules this module enforces, so callers cannot get them wrong:
// - Attribution is the server's: an item served by a ranked surface carries the
//   serve token `st` it came with, and nothing else. `cfg` and `variant` are
//   never sent; every event is rebuilt from an allow-list of fields.
// - No personal data: ids, enums, counters and timestamps only.
// - Dedupe: one impression, one open and one dwell per (session, item); one
//   profile visit per (profile, UTC day); video progress at most once per 5 s per item.
// - The session (R3 WP 4b.2): `sessionId`, its last activity and the dedupe set
//   live in sessionStorage, so a reload in the same tab keeps the session and
//   sends no second impression for an item already reported. Storage that throws
//   (private mode, blocked) falls back to memory for this page.
// - Batching: flush every 10 s, at 30 queued events, and when the tab is hidden
//   (fetch keepalive: sendBeacon cannot carry the bearer header). At most 50
//   events and 32 KB per batch; at most 200 events held in memory (oldest go).
// - With personalization off nothing is queued and no request is made.
// - A retried batch keeps its batch_id, so the server stores it once.
import { api } from "./api";
import { isTokenExpired, tokenStore } from "./tokens";

export const SIGNAL_LIMITS = {
  flushMs: 10_000,
  flushAt: 30,
  maxBatch: 50,
  maxBatchBytes: 32 * 1024,
  maxQueue: 200,
  sessionIdleMs: 30 * 60_000,
  progressGapMs: 5_000,
  maxRetries: 3,
  maxServed: 1_000,
  maxSeen: 5_000,
} as const;

export const SIGNAL_SURFACES = ["home", "reels", "video", "groups", "marketplace", "discovery", "profile", "search", "link"] as const;
export type SignalSurface = (typeof SIGNAL_SURFACES)[number];

/** Event types a client may send; everything else is the server's (bus or server actions). */
export const CLIENT_SIGNAL_TYPES = [
  "feed_impression",
  "post_open",
  "video_start",
  "video_progress",
  "video_complete",
  "video_rewatch",
  "video_skip",
  "reel_view",
  "profile_visit",
  "feed_dwell",
] as const;
export type ClientSignalType = (typeof CLIENT_SIGNAL_TYPES)[number];

const ITEM_TYPES = ["post", "reel", "video", "profile", "page", "group", "listing"];
const ITEM_RE = /^([a-z]+):([0-9a-fA-F-]{36})$/;

export interface SignalInput {
  t: ClientSignalType;
  /** `<type>:<uuid>`, e.g. `post:…`, `reel:…`, `video:…`, `profile:…`, `page:…`. */
  item: string;
  /** Where it was seen; sent only when no serve token attributes it. */
  surface?: SignalSurface;
  pos?: number;
  watch_ms?: number;
  pos_ms?: number;
  play_index?: number;
  /** Impressions only: the impression rule the client applied (08 §7.12; 1 = legacy). */
  idef?: number;
  /** `feed_dwell` only: accumulated time the card met the impression rule (R3 WP 4b.2). */
  dwell_ms?: number;
}

/** The wire shape: exactly these fields, never `cfg` or `variant`. */
export interface SignalEvent {
  id: string;
  t: ClientSignalType;
  item: string;
  ts: string;
  st?: string;
  surface?: SignalSurface;
  pos?: number;
  watch_ms?: number;
  pos_ms?: number;
  play_index?: number;
  idef?: number;
  dwell_ms?: number;
}

interface Batch {
  batch_id: string;
  session_id: string;
  events: SignalEvent[];
  attempts: number;
}

interface Served {
  st?: string;
  pos?: number;
  surface: SignalSurface;
}

const state = {
  queue: [] as SignalEvent[],
  retry: [] as Batch[],
  served: new Map<string, Served>(),
  seen: new Map<string, true>(),
  lastProgress: new Map<string, number>(),
  sessionId: "",
  lastActivity: 0,
  off: false,
  disabled: false,
  timer: null as ReturnType<typeof setInterval> | null,
  listening: false,
  sending: false,
  restored: false,
  persistTimer: null as ReturnType<typeof setTimeout> | null,
};

// The tab's session in sessionStorage (R3 WP 4b.2): ids and timestamps only.
const SESSION_KEY = "tara.signals.session.v1";
const PERSIST_MS = 500;
// The dedupe keys kept across a reload (the newest; the in-memory set keeps maxSeen).
const PERSIST_SEEN = 2_000;

interface StoredSession {
  sid: string;
  last: number;
  seen: string[];
}

function restore() {
  if (state.restored) return;
  state.restored = true;
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return;
    const s = JSON.parse(raw) as Partial<StoredSession>;
    if (typeof s.sid !== "string" || !/^[0-9a-f-]{36}$/i.test(s.sid) || typeof s.last !== "number") return;
    if (state.sessionId) return; // this page already started its own
    state.sessionId = s.sid;
    state.lastActivity = s.last;
    for (const k of Array.isArray(s.seen) ? s.seen : []) if (typeof k === "string") state.seen.set(k, true);
  } catch {
    // Blocked or junk: this page keeps its session in memory.
  }
}

function persistNow() {
  if (state.persistTimer) clearTimeout(state.persistTimer);
  state.persistTimer = null;
  if (!state.sessionId) return;
  try {
    const seen = [...state.seen.keys()].slice(-PERSIST_SEEN);
    const stored: StoredSession = { sid: state.sessionId, last: state.lastActivity, seen };
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(stored));
  } catch {
    // Storage blocked or full: the session lives in memory for this page.
  }
}

function persistSoon() {
  if (!state.persistTimer) state.persistTimer = setTimeout(persistNow, PERSIST_MS);
}

function forgetStored() {
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // Nothing stored.
  }
}

function uuid(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c?.randomUUID) return c.randomUUID();
  const b = new Uint8Array(16);
  if (c?.getRandomValues) c.getRandomValues(b);
  else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

/** The tab's session id; a new one after 30 minutes without a signal. */
function session(now: number): string {
  restore();
  if (!state.sessionId || now - state.lastActivity > SIGNAL_LIMITS.sessionIdleMs) {
    state.sessionId = uuid();
    state.seen.clear();
    state.lastProgress.clear();
  }
  state.lastActivity = now;
  persistSoon();
  return state.sessionId;
}

/**
 * The tab's telemetry session id, sent as the `sid` hint of a Home first page
 * (06 §4.2). Undefined with personalization off or signed out: nothing about
 * the visit is offered then.
 */
export function signalSessionId(now = Date.now()): string | undefined {
  if (state.off || !tokenStore.access) return undefined;
  return session(now);
}

function remember<K, V>(map: Map<K, V>, key: K, value: V, cap: number) {
  map.delete(key);
  map.set(key, value);
  while (map.size > cap) map.delete(map.keys().next().value as K);
}

/** `post:<uuid>` for an item id and kind. */
export function itemKey(kind: string, id: string): string {
  return `${kind}:${id}`;
}

/** The uuid of an `<type>:<uuid>` item: serve tokens are matched by it, so a
 * video watched in a served post (`video:<id>`) carries that post's token. */
const itemId = (item: string): string | null => ITEM_RE.exec(item)?.[2]?.toLowerCase() ?? null;

/**
 * A ranked surface served this item: keep its serve token (and position) so the
 * events about it are attributed by the server. Called by the code that loads
 * the surface (Home, Reels), never by a card.
 */
export function noteServed(item: string, served: Served) {
  const id = itemId(item);
  if (!id) return;
  const st = typeof served.st === "string" && served.st ? served.st : undefined;
  remember(state.served, id, { ...served, st }, SIGNAL_LIMITS.maxServed);
}

/** The serve token an item was served with, if any ("Why am I seeing this?", WP 4.8). */
export function servedToken(item: string): string | undefined {
  const id = itemId(item);
  return id ? state.served.get(id)?.st : undefined;
}

/** The served position of an item, when a ranked surface served it. */
export function servedPosition(item: string): number | undefined {
  const id = itemId(item);
  return id ? state.served.get(id)?.pos : undefined;
}

function dedupeKey(input: SignalInput, sessionId: string, now: number): string | null {
  if (input.t === "feed_impression" || input.t === "post_open" || input.t === "feed_dwell")
    return `${sessionId}|${input.t}|${input.item}`;
  if (input.t === "profile_visit") return `${input.t}|${input.item}|${new Date(now).toISOString().slice(0, 10)}`;
  return null;
}

const whole = (n: unknown): number | undefined =>
  typeof n === "number" && Number.isFinite(n) && n >= 0 ? Math.round(n) : undefined;

/** Queue one signal. Returns whether it was queued (false: off, invalid or a duplicate). */
export function track(input: SignalInput): boolean {
  if (state.off || state.disabled || !tokenStore.access) return false; // signed-in viewers only
  if (!(CLIENT_SIGNAL_TYPES as readonly string[]).includes(input.t)) return false;
  const match = ITEM_RE.exec(input.item);
  if (!match || !ITEM_TYPES.includes(match[1])) return false;
  const now = Date.now();
  const sessionId = session(now);
  const key = dedupeKey(input, sessionId, now);
  if (key) {
    if (state.seen.has(key)) return false;
    remember(state.seen, key, true, SIGNAL_LIMITS.maxSeen);
  }
  if (input.t === "video_progress") {
    const last = state.lastProgress.get(input.item);
    if (last !== undefined && now - last < SIGNAL_LIMITS.progressGapMs) return false;
    remember(state.lastProgress, input.item, now, SIGNAL_LIMITS.maxSeen);
  }
  const served = state.served.get(match[2].toLowerCase());
  const event: SignalEvent = { id: uuid(), t: input.t, item: input.item, ts: new Date(now).toISOString() };
  if (served?.st) event.st = served.st;
  else {
    const surface = input.surface ?? served?.surface;
    if (surface && (SIGNAL_SURFACES as readonly string[]).includes(surface)) event.surface = surface;
  }
  // The feed position belongs to impressions; the server reads it from the token when there is one.
  const pos = input.t === "feed_impression" ? whole(input.pos ?? served?.pos) : undefined;
  if (pos !== undefined) event.pos = pos;
  // The impression definition (08 §7.12): a whole number ≥ 1, impressions only.
  const idef = input.t === "feed_impression" ? whole(input.idef) : undefined;
  if (idef !== undefined && idef >= 1) event.idef = idef;
  // The dwell (R3 WP 4b.2): `feed_dwell` only, never on another type.
  const dwell = input.t === "feed_dwell" ? whole(input.dwell_ms) : undefined;
  if (input.t === "feed_dwell") {
    if (dwell === undefined) return false;
    event.dwell_ms = dwell;
  }
  for (const field of ["watch_ms", "pos_ms", "play_index"] as const) {
    const value = whole(input[field]);
    if (value !== undefined) event[field] = value;
  }
  state.queue.push(event);
  if (state.queue.length > SIGNAL_LIMITS.maxQueue) state.queue.splice(0, state.queue.length - SIGNAL_LIMITS.maxQueue);
  start();
  if (state.queue.length >= SIGNAL_LIMITS.flushAt) void flush();
  return true;
}

function onVisibility() {
  if (document.visibilityState === "hidden") {
    persistNow();
    void flush({ keepalive: true });
  }
}

function start() {
  if (!state.timer) state.timer = setInterval(() => void flush(), SIGNAL_LIMITS.flushMs);
  if (!state.listening && typeof document !== "undefined") {
    document.addEventListener("visibilitychange", onVisibility);
    state.listening = true;
  }
}

function stop() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
  if (state.listening && typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisibility);
  state.listening = false;
}

/** The next batch from the queue: at most 50 events and 32 KB. */
function takeBatch(): Batch | null {
  if (!state.queue.length) return null;
  const events: SignalEvent[] = [];
  let bytes = 120; // the envelope around the events
  while (state.queue.length && events.length < SIGNAL_LIMITS.maxBatch) {
    const size = JSON.stringify(state.queue[0]).length + 1;
    if (events.length && bytes + size > SIGNAL_LIMITS.maxBatchBytes) break;
    events.push(state.queue.shift() as SignalEvent);
    bytes += size;
  }
  return { batch_id: uuid(), session_id: state.sessionId || session(Date.now()), events, attempts: 0 };
}

function endpoint(): string {
  return `${String(api.defaults.baseURL ?? "").replace(/\/$/, "")}/feed/signals/`;
}

type Outcome = "sent" | "drop" | "retry" | "disable" | "wait";

async function send(batch: Batch, keepalive: boolean): Promise<Outcome> {
  const access = tokenStore.access;
  if (!access || isTokenExpired(access)) return "wait"; // the api client refreshes; try later
  try {
    const resp = await fetch(endpoint(), {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${access}` },
      body: JSON.stringify({ batch_id: batch.batch_id, session_id: batch.session_id, events: batch.events }),
      keepalive,
      credentials: "include",
    });
    if (resp.ok) return "sent";
    if (resp.status === 404 || resp.status === 405) return "disable"; // no signals endpoint on this server
    if (resp.status === 429 || resp.status >= 500) return "retry";
    return "drop"; // 400 / 401 / 403 / 413: resending the same batch cannot help
  } catch {
    return "retry";
  }
}

/** Send what is queued. `keepalive` when the page may be going away. */
export async function flush({ keepalive = false }: { keepalive?: boolean } = {}): Promise<void> {
  if (state.off || state.disabled || state.sending) return;
  state.sending = true;
  try {
    for (;;) {
      const batch = state.retry.shift() ?? takeBatch();
      if (!batch) break;
      const outcome = await send(batch, keepalive);
      if (state.off) break; // switched off mid-flight: nothing else goes out
      if (outcome === "disable") {
        disable();
        break;
      }
      if (outcome === "wait" || outcome === "retry") {
        batch.attempts += outcome === "retry" ? 1 : 0;
        if (batch.attempts < SIGNAL_LIMITS.maxRetries) state.retry.unshift(batch);
        break;
      }
    }
  } finally {
    state.sending = false;
  }
  if (!state.queue.length && !state.retry.length) stop();
}

function disable() {
  state.disabled = true;
  state.queue = [];
  state.retry = [];
  stop();
}

/** The viewer's "turn off personalization" switch: while on, nothing is collected or sent. */
export function setPersonalizationOff(off: boolean) {
  state.off = off;
  if (off) {
    state.queue = [];
    state.retry = [];
    stop();
    // Nothing about this tab's session stays behind either.
    if (state.persistTimer) clearTimeout(state.persistTimer);
    state.persistTimer = null;
    forgetStored();
  }
}

export function personalizationOff(): boolean {
  return state.off;
}

/** Forget everything (sign-out, or another account signs in). */
export function resetSignals() {
  stop();
  state.queue = [];
  state.retry = [];
  state.served.clear();
  state.seen.clear();
  state.lastProgress.clear();
  state.sessionId = "";
  state.lastActivity = 0;
  state.off = false;
  state.disabled = false;
  state.sending = false;
  if (state.persistTimer) clearTimeout(state.persistTimer);
  state.persistTimer = null;
  state.restored = false;
  forgetStored();
}

/** Tests: a full reload of the tab (memory gone, sessionStorage kept). */
export function simulateReloadForTests() {
  persistNow();
  stop();
  state.queue = [];
  state.retry = [];
  state.served.clear();
  state.seen.clear();
  state.lastProgress.clear();
  state.sessionId = "";
  state.lastActivity = 0;
  state.restored = false;
}

/** For tests and the dev tools: what is waiting to be sent. */
export function pendingSignals(): readonly SignalEvent[] {
  return [...state.retry.flatMap((b) => b.events), ...state.queue];
}

/** The signals surface a route belongs to (an item opened outside a ranked surface). */
export function surfaceForRoute(name: unknown): SignalSurface {
  switch (name) {
    case "home":
      return "home";
    case "reels":
    case "reel":
      return "reels";
    case "videos":
      return "video";
    case "group":
    case "groups":
      return "groups";
    case "profile":
    case "profile-by-id":
    case "page":
    case "page-by-id":
      return "profile";
    case "search":
      return "search";
    case "marketplace":
    case "listing":
      return "marketplace";
    default:
      return "link";
  }
}
