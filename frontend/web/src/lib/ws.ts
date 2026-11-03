// Realtime gateway client (Django Channels). Authenticates with the access
// token as the first `Sec-WebSocket-Protocol` entry (never in the URL, which
// ends up in proxy and access logs), auto-reconnects with capped exponential
// backoff, and fans incoming frames out to topic subscribers. No DB;
// presence/typing/receipts and live message/notification frames flow through here.
//
// Pushes sent while the socket is down are lost for good (the gateway keeps no
// history), so a `_reconnected` frame tells subscribers to refetch over REST.
import { ensureFreshAccess, notifyUnauthorized } from "./api";
import { tokenStore } from "./tokens";

// Gateway frames are keyed by `event` (e.g. "chat.message.created",
// "conversation.typing", "notification.created"); our internal status frames use
// `type` ("_status", "_reconnected"). A gateway frame's own `type` is payload
// (a message or reaction type), so `type` only dispatches internal frames.
type Frame = { type?: string; event?: string; [k: string]: unknown };
type Handler = (frame: Frame) => void;

const HEARTBEAT_MS = 30_000;
const PONG_TIMEOUT_MS = 2 * HEARTBEAT_MS + 10_000;
const MAX_QUEUED = 50;

// Resolve the realtime endpoint. In production the app is same-origin behind
// nginx, so VITE_WS_URL is a relative path (or empty) and we derive the absolute
// ws(s):// URL from the current page. An absolute VITE_WS_URL (dev) is used as-is.
function resolveWsBase(): string {
  const configured = import.meta.env.VITE_WS_URL;
  if (configured && /^wss?:\/\//i.test(configured)) return configured;
  const path = configured && configured.startsWith("/") ? configured : "/ws/v1/";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}

const WS_BASE = resolveWsBase();

export class RealtimeClient {
  private socket: WebSocket | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private backoff = 1000;
  private readonly maxBackoff = 30000;
  private closedByUser = false;
  private reconnectTimer: number | null = null;
  private heartbeatTimer: number | null = null;
  private lastPongAt = 0;
  private opening = false;
  private everOpened = false;
  private queue: Frame[] = [];
  private conversations = new Set<string>();

  /** Current connection state, surfaced to the UI for an offline banner. */
  status: "connecting" | "open" | "closed" = "closed";

  connect() {
    if (!tokenStore.access && !tokenStore.refresh) return;
    this.closedByUser = false;
    if (this.opening || this.socket) return;
    void this.open();
  }

  private async open() {
    this.opening = true;
    this.status = "connecting";
    // The token is only checked at connect time, and a reconnect can happen long
    // after it expired: a rejected handshake just looks like a dropped socket.
    const fresh = await ensureFreshAccess();
    this.opening = false;
    if (this.closedByUser) return;
    if (fresh === "invalid") {
      this.status = "closed";
      notifyUnauthorized();
      return;
    }
    if (fresh === "unavailable") {
      this.status = "closed";
      this.scheduleReconnect();
      return;
    }

    // The token travels as the subprotocol, never in the URL, where proxies
    // and access logs would keep it.
    const sock = new WebSocket(WS_BASE, [tokenStore.access ?? ""]);
    this.socket = sock;

    sock.onopen = () => {
      this.status = "open";
      this.backoff = 1000;
      this.startHeartbeat();
      this.conversations.forEach((id) => this.write({ action: "subscribe", conversation_id: id }));
      this.queue.splice(0).forEach((frame) => this.write(frame));
      this.emit({ type: "_status", status: "open" });
      if (this.everOpened) this.emit({ type: "_reconnected" });
      this.everOpened = true;
    };
    sock.onmessage = (ev) => {
      try {
        const frame = JSON.parse(ev.data) as Frame;
        if (frame.event === "pong") this.lastPongAt = Date.now();
        this.emit(frame);
      } catch {
        // Ignore malformed frames; the gateway only sends JSON.
      }
    };
    sock.onclose = () => {
      if (this.socket !== sock) return;
      this.socket = null;
      this.stopHeartbeat();
      this.status = "closed";
      this.emit({ type: "_status", status: "closed" });
      if (!this.closedByUser) this.scheduleReconnect();
    };
    sock.onerror = () => sock.close();
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return;
    const delay = this.backoff;
    this.backoff = Math.min(this.backoff * 2, this.maxBackoff);
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.closedByUser) void this.open();
    }, delay);
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.lastPongAt = Date.now();
    this.heartbeatTimer = window.setInterval(() => {
      // A half-open connection never reports an error; only silence gives it away.
      if (Date.now() - this.lastPongAt > PONG_TIMEOUT_MS) {
        this.socket?.close();
        return;
      }
      this.write({ action: "ping" });
    }, HEARTBEAT_MS);
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) window.clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }

  private write(frame: Frame) {
    this.socket?.send(JSON.stringify(frame));
  }

  private emit(frame: Frame) {
    const internal = typeof frame.type === "string" && frame.type.startsWith("_") ? frame.type : null;
    for (const key of new Set([internal, frame.event])) {
      if (typeof key === "string") this.handlers.get(key)?.forEach((h) => h(frame));
    }
    this.handlers.get("*")?.forEach((h) => h(frame));
  }

  /** Subscribe to a frame `event`/`type` ("*" for all). Returns an unsubscribe fn. */
  on(type: string, handler: Handler): () => void {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set());
    this.handlers.get(type)!.add(handler);
    return () => this.handlers.get(type)?.delete(handler);
  }

  /** Send now, or once the socket opens. Conversation subscriptions survive reconnects. */
  send(frame: Frame) {
    const open = this.socket?.readyState === WebSocket.OPEN;
    const conversationId = frame.conversation_id as string;
    if (frame.action === "subscribe") this.conversations.add(conversationId);
    if (frame.action === "unsubscribe") this.conversations.delete(conversationId);

    if (open) {
      this.write(frame);
    } else if (frame.action !== "subscribe" && frame.action !== "unsubscribe" && frame.action !== "typing") {
      // Subscriptions are replayed on open; a late typing signal would be a lie.
      this.queue.push(frame);
      if (this.queue.length > MAX_QUEUED) this.queue.shift();
    }
  }

  close() {
    this.closedByUser = true;
    if (this.reconnectTimer) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopHeartbeat();
    this.socket?.close();
    this.socket = null;
    this.queue = [];
    this.conversations.clear();
    this.everOpened = false;
    this.status = "closed";
  }
}

export const realtime = new RealtimeClient();
