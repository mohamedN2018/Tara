// Realtime gateway client (Django Channels). Authenticates with the access
// token as a query param, auto-reconnects with capped exponential backoff, and
// fans incoming frames out to topic subscribers. No DB; presence/typing/receipts
// and live message/notification frames flow through here.
import { tokenStore } from "./tokens";

// Gateway frames are keyed by `event` (e.g. "chat.message.created",
// "conversation.typing", "notification.created"); our internal status frame uses
// `type` ("_status"). We dispatch on both so handlers can subscribe by either.
type Frame = { type?: string; event?: string; [k: string]: unknown };
type Handler = (frame: Frame) => void;

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

class RealtimeClient {
  private socket: WebSocket | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private backoff = 1000;
  private readonly maxBackoff = 30000;
  private closedByUser = false;
  private reconnectTimer: number | null = null;

  /** Current connection state, surfaced to the UI for an offline banner. */
  status: "connecting" | "open" | "closed" = "closed";

  connect() {
    if (!tokenStore.access) return;
    this.closedByUser = false;
    this.open();
  }

  private open() {
    this.status = "connecting";
    const url = `${WS_BASE}?token=${encodeURIComponent(tokenStore.access ?? "")}`;
    const sock = new WebSocket(url);
    this.socket = sock;

    sock.onopen = () => {
      this.status = "open";
      this.backoff = 1000;
      this.emit({ type: "_status", status: "open" });
    };
    sock.onmessage = (ev) => {
      try {
        const frame = JSON.parse(ev.data) as Frame;
        this.emit(frame);
      } catch {
        // Ignore malformed frames; the gateway only sends JSON.
      }
    };
    sock.onclose = () => {
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
      if (!this.closedByUser) this.open();
    }, delay);
  }

  private emit(frame: Frame) {
    const seen = new Set<string>();
    for (const key of [frame.type, frame.event]) {
      if (typeof key === "string" && !seen.has(key)) {
        seen.add(key);
        this.handlers.get(key)?.forEach((h) => h(frame));
      }
    }
    this.handlers.get("*")?.forEach((h) => h(frame));
  }

  /** Subscribe to a frame `event`/`type` ("*" for all). Returns an unsubscribe fn. */
  on(type: string, handler: Handler): () => void {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set());
    this.handlers.get(type)!.add(handler);
    return () => this.handlers.get(type)?.delete(handler);
  }

  send(frame: Frame) {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(frame));
    }
  }

  close() {
    this.closedByUser = true;
    if (this.reconnectTimer) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
    this.socket = null;
    this.status = "closed";
  }
}

export const realtime = new RealtimeClient();
