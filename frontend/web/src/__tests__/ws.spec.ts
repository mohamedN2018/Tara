import axios from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setUnauthorizedHandler } from "@/lib/api";
import { tokenStore } from "@/lib/tokens";
import { RealtimeClient } from "@/lib/ws";

const token = (exp: number) => `h.${btoa(JSON.stringify({ exp }))}.s`;
const now = () => Math.floor(Date.now() / 1000);

class FakeSocket {
  static OPEN = 1;
  static instances: FakeSocket[] = [];
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(
    public url: string,
    public protocols?: string[],
  ) {
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  accept() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }
}

const latest = () => FakeSocket.instances[FakeSocket.instances.length - 1];
const flush = () => vi.advanceTimersByTimeAsync(0);

describe("RealtimeClient", () => {
  let client: RealtimeClient;

  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    FakeSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeSocket);
    tokenStore.set(token(now() + 3600), "r1");
    client = new RealtimeClient();
  });

  afterEach(() => {
    client.close();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("queues sends until the socket opens", async () => {
    client.connect();
    client.send({ action: "note" });
    await flush();
    latest().accept();
    expect(latest().sent).toEqual([{ action: "note" }]);
  });

  it("drops typing frames instead of delivering them late", async () => {
    client.connect();
    client.send({ action: "typing", conversation_id: "c1" });
    await flush();
    latest().accept();
    expect(latest().sent).toEqual([]);
  });

  it("re-subscribes to conversations after a reconnect, and signals it", async () => {
    const reconnected = vi.fn();
    client.on("_reconnected", reconnected);
    client.connect();
    await flush();
    latest().accept();
    expect(reconnected).not.toHaveBeenCalled();
    client.send({ action: "subscribe", conversation_id: "c1" });
    client.send({ action: "subscribe", conversation_id: "c2" });
    client.send({ action: "unsubscribe", conversation_id: "c2" });

    latest().close();
    await vi.advanceTimersByTimeAsync(1100);
    latest().accept();

    expect(latest().sent).toEqual([{ action: "subscribe", conversation_id: "c1" }]);
    expect(reconnected).toHaveBeenCalledOnce();
  });

  it("refreshes an expired access token before reconnecting", async () => {
    client.connect();
    await flush();
    latest().accept();

    const fresh = token(now() + 3600);
    tokenStore.set(token(now() - 10), "r1");
    const post = vi.spyOn(axios, "post").mockResolvedValue({
      data: { data: { access_token: fresh, refresh_token: "r2" } },
    });
    latest().close();
    await vi.advanceTimersByTimeAsync(1100);

    expect(post).toHaveBeenCalledOnce();
    expect(latest().protocols).toEqual([fresh]);
  });

  it("sends the token as a subprotocol, never in the URL", async () => {
    client.connect();
    await flush();
    expect(latest().url).not.toContain("token");
    expect(latest().protocols).toEqual([tokenStore.access]);
  });

  it("never puts the token in the URL, even after a refused handshake", async () => {
    client.connect();
    await flush();
    latest().close(); // refused before opening
    await vi.advanceTimersByTimeAsync(1100);
    latest().accept();
    latest().close(); // and a dropped socket later on
    await vi.advanceTimersByTimeAsync(2100);
    expect(FakeSocket.instances.length).toBeGreaterThanOrEqual(3);
    expect(FakeSocket.instances.every((s) => !s.url.includes("token"))).toBe(true);
    expect(FakeSocket.instances.every((s) => s.protocols?.[0] === tokenStore.access)).toBe(true);
  });

  it("dispatches gateway frames by event, not by their payload type", async () => {
    const byPayload = vi.fn();
    const byEvent = vi.fn();
    client.on("image", byPayload);
    client.on("chat.message.created", byEvent);
    client.connect();
    await flush();
    latest().accept();
    latest().onmessage?.({ data: JSON.stringify({ event: "chat.message.created", type: "image" }) });
    expect(byEvent).toHaveBeenCalledOnce();
    expect(byPayload).not.toHaveBeenCalled();
  });

  it("stops and reports when the session is over", async () => {
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    tokenStore.set(token(now() - 10), "r1");
    vi.spyOn(axios, "post").mockRejectedValue({ response: { status: 401 } });
    client.connect();
    await flush();
    expect(FakeSocket.instances).toHaveLength(0);
    expect(unauthorized).toHaveBeenCalledOnce();
  });

  it("keeps retrying while refresh is merely unavailable", async () => {
    tokenStore.set(token(now() - 10), "r1");
    const post = vi.spyOn(axios, "post").mockRejectedValue({ response: { status: 503 } });
    client.connect();
    await vi.advanceTimersByTimeAsync(1100);
    expect(post).toHaveBeenCalledTimes(2);
    expect(tokenStore.refresh).toBe("r1");
  });

  it("sends a ping every 30s and drops a connection that stopped answering", async () => {
    client.connect();
    await flush();
    const socket = latest();
    socket.accept();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(socket.sent).toEqual([{ action: "ping" }]);
    socket.onmessage?.({ data: JSON.stringify({ event: "pong" }) });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(socket.sent).toHaveLength(2);
    expect(socket.readyState).toBe(FakeSocket.OPEN);

    await vi.advanceTimersByTimeAsync(120_000);
    expect(socket.readyState).toBe(3);
  });

  it("does not open a second socket when connect is called twice", async () => {
    client.connect();
    client.connect();
    await flush();
    client.connect();
    await flush();
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("close stops reconnecting", async () => {
    client.connect();
    await flush();
    latest().accept();
    client.close();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });
});
