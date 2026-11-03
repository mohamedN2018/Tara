import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { callLogKey, formatDuration, parseCallLog } from "@/lib/callLog";
import { realtime } from "@/lib/ws";
import { type Call, type CallJoin, callService } from "@/services/calls";
import { useAuthStore } from "@/stores/auth";
import { mediaErrorKey, useCallStore } from "@/stores/calls";

// ---- a fake LiveKit room -----------------------------------------------------------

const lk = vi.hoisted(() => {
  type Handler = (...args: unknown[]) => void;
  class FakeLocal {
    identity = "me";
    isSpeaking = false;
    isMicrophoneEnabled = false;
    isCameraEnabled = false;
    isScreenShareEnabled = false;
    audioTrackPublications = new Map();
    cameraError: Error | null = null;
    getTrackPublication() {
      return undefined;
    }
    async setMicrophoneEnabled(on: boolean) {
      this.isMicrophoneEnabled = on;
    }
    async setCameraEnabled(on: boolean) {
      if (on && this.cameraError) throw this.cameraError;
      this.isCameraEnabled = on;
    }
    async setScreenShareEnabled(on: boolean) {
      this.isScreenShareEnabled = on;
    }
  }
  class FakeRoom {
    static instances: FakeRoom[] = [];
    static nextCameraError: Error | null = null;
    static gate: Promise<void> | null = null;
    handlers = new Map<string, Handler[]>();
    localParticipant = new FakeLocal();
    remoteParticipants = new Map();
    canPlaybackAudio = true;
    connected: { url: string; token: string } | null = null;
    disconnected = false;
    connectGate: Promise<void> | null = null;
    constructor() {
      this.localParticipant.cameraError = FakeRoom.nextCameraError;
      this.connectGate = FakeRoom.gate;
      FakeRoom.instances.push(this);
    }
    on(event: string, handler: Handler) {
      this.handlers.set(event, [...(this.handlers.get(event) ?? []), handler]);
      return this;
    }
    emit(event: string, ...args: unknown[]) {
      (this.handlers.get(event) ?? []).forEach((h) => h(...args));
    }
    removeAllListeners() {
      this.handlers.clear();
      return this;
    }
    async connect(url: string, token: string) {
      if (this.connectGate) await this.connectGate;
      this.connected = { url, token };
    }
    async disconnect() {
      this.disconnected = true;
      this.emit("disconnected");
    }
    getActiveDevice() {
      return undefined;
    }
    async switchActiveDevice() {
      return true;
    }
    async startAudio() {}
    static async getLocalDevices() {
      return [];
    }
  }
  return { FakeRoom };
});

vi.mock("livekit-client", () => ({
  Room: lk.FakeRoom,
  RoomEvent: new Proxy({}, { get: (_t, key) => String(key).charAt(0).toLowerCase() + String(key).slice(1) }),
  Track: { Source: { Camera: "camera", Microphone: "microphone", ScreenShare: "screen_share" } },
}));

const tones = vi.hoisted(() => ({ start: vi.fn(() => true), stop: vi.fn() }));
vi.mock("@/lib/ringtone", () => ({ startTone: tones.start, stopTone: tones.stop, toneActive: () => false }));

// ---- helpers -------------------------------------------------------------------------

const ME = "me";
const PEER = "peer";

function aCall(over: Partial<Call> = {}): Call {
  return {
    id: "call1",
    conversation_id: "conv1",
    conversation_type: "dm",
    kind: "audio",
    state: "ringing",
    initiator_id: ME,
    created_at: new Date().toISOString(),
    answered_at: null,
    ended_at: null,
    end_reason: "",
    duration_s: 0,
    ring_expires_at: new Date(Date.now() + 45_000).toISOString(),
    participants: [
      { account_id: ME, state: "accepted", in_room: false },
      { account_id: PEER, state: "ringing", in_room: false },
    ],
    ...over,
  };
}

function joined(call: Call, token = "tok-1"): CallJoin {
  return { call_id: call.id, room: "room-x", token, url: "ws://lk.test", call };
}

function ring(over: Record<string, unknown> = {}) {
  return {
    event: "call.ringing",
    call_id: "call1",
    conversation_id: "conv1",
    conversation_type: "dm",
    kind: "audio",
    initiator: PEER,
    expires_at: new Date(Date.now() + 45_000).toISOString(),
    ...over,
  };
}

const rooms = () => lk.FakeRoom.instances;
const flush = () => new Promise((r) => setTimeout(r, 0));

function enabledStore() {
  const store = useCallStore();
  store.config = { enabled: true, ring_timeout_s: 45, max_participants: 16 };
  return store;
}

beforeEach(() => {
  setActivePinia(createPinia());
  useAuthStore().account = { id: ME } as never;
  lk.FakeRoom.instances = [];
  lk.FakeRoom.nextCameraError = null;
  lk.FakeRoom.gate = null;
  tones.start.mockClear();
  tones.stop.mockClear();
  // Frames re-check the conversation's live call; tests that care override this.
  vi.spyOn(callService, "active").mockResolvedValue(null);
});

afterEach(() => {
  vi.useRealTimers();
});

// ---- tests ----------------------------------------------------------------------------

describe("call config", () => {
  it("stays off when the config cannot be loaded, and then nothing starts", async () => {
    vi.spyOn(callService, "config").mockRejectedValue(new Error("down"));
    const start = vi.spyOn(callService, "start");
    const store = useCallStore();
    await store.loadConfig();
    expect(store.enabled).toBe(false);
    await store.start("conv1", "audio");
    expect(start).not.toHaveBeenCalled();
    expect(store.phase).toBe("idle");
  });

  it("ignores rings while calls are off", () => {
    const store = useCallStore();
    store.onRinging(ring());
    expect(store.phase).toBe("idle");
  });
});

describe("outgoing call", () => {
  it("rings, moves to in_call when answered, and hangs up cleanly", async () => {
    vi.useFakeTimers();
    const store = enabledStore();
    vi.spyOn(callService, "start").mockResolvedValue(joined(aCall()));
    const end = vi.spyOn(callService, "end").mockResolvedValue(aCall({ state: "ended" }));

    await store.start("conv1", "audio");
    expect(store.phase).toBe("outgoing");
    expect(tones.start).toHaveBeenCalledWith("outgoing", expect.anything());
    expect(rooms()).toHaveLength(1);
    expect(rooms()[0].connected).toEqual({ url: "ws://lk.test", token: "tok-1" });
    expect(store.micOn).toBe(true);

    store.onAnswered({ call_id: "call1", conversation_id: "conv1", account: PEER });
    expect(store.phase).toBe("in_call");
    expect(tones.stop).toHaveBeenCalled();
    vi.advanceTimersByTime(3000);
    expect(store.duration).toBeGreaterThanOrEqual(3);

    await store.hangup();
    expect(end).toHaveBeenCalledWith("call1");
    expect(rooms()[0].disconnected).toBe(true);
    expect(store.phase).toBe("ended");
    expect(store.endReason).toBe("ended");
    expect(store.tiles).toEqual([]);
    vi.advanceTimersByTime(3000);
    expect(store.phase).toBe("idle");
    expect(store.call).toBeNull();
  });

  it("joining a live call goes straight to in_call", async () => {
    const store = enabledStore();
    const live = aCall({ state: "active", initiator_id: PEER, answered_at: new Date().toISOString() });
    vi.spyOn(callService, "start").mockResolvedValue(joined(live));
    await store.start("conv1", "audio");
    expect(store.phase).toBe("in_call");
  });

  it("ends with no_answer when the call is missed", async () => {
    const store = enabledStore();
    vi.spyOn(callService, "start").mockResolvedValue(joined(aCall()));
    await store.start("conv1", "audio");
    store.onMissed({ call_id: "call1", conversation_id: "conv1", final: true, missed: [PEER] });
    expect(store.phase).toBe("ended");
    expect(store.endReason).toBe("no_answer");
    expect(rooms()[0].disconnected).toBe(true);
  });

  it("ends with declined when the other side declines a DM call", async () => {
    const store = enabledStore();
    vi.spyOn(callService, "start").mockResolvedValue(joined(aCall()));
    await store.start("conv1", "audio");
    store.onDeclined({ call_id: "call1", conversation_id: "conv1", account: PEER });
    expect(store.call?.participants.find((p) => p.account_id === PEER)?.state).toBe("declined");
    store.onEnded({ call_id: "call1", conversation_id: "conv1", reason: "declined", duration_s: 0 });
    expect(store.endReason).toBe("declined");
  });

  it("turns calls off when the server says they are unavailable", async () => {
    const store = enabledStore();
    vi.spyOn(callService, "start").mockRejectedValue({
      isAxiosError: true,
      response: { status: 503, data: { error: { code: "calls_unavailable", message: "off" } } },
    });
    await store.start("conv1", "audio");
    expect(store.phase).toBe("ended");
    expect(store.endReason).toBe("unavailable");
    expect(store.enabled).toBe(false);
  });

  it("a video call without a camera carries on as a voice call", async () => {
    const store = enabledStore();
    lk.FakeRoom.nextCameraError = Object.assign(new Error("denied"), { name: "NotAllowedError" });
    vi.spyOn(callService, "start").mockResolvedValue(joined(aCall({ kind: "video" })));
    await store.start("conv1", "video");
    expect(store.micOn).toBe(true);
    expect(store.camOn).toBe(false);
    expect(store.notice).toBe("calls.errors.cameraDeniedFallback");
  });

  it("hanging up while connecting drops the room as soon as it connects", async () => {
    const store = enabledStore();
    let open!: () => void;
    lk.FakeRoom.gate = new Promise<void>((r) => (open = r));
    vi.spyOn(callService, "start").mockResolvedValue(joined(aCall()));
    const end = vi.spyOn(callService, "end").mockResolvedValue(aCall({ state: "missed" }));
    const starting = store.start("conv1", "audio");
    await flush();
    expect(rooms()).toHaveLength(1);
    await store.hangup();
    expect(end).toHaveBeenCalledWith("call1");
    open();
    await starting;
    expect(store.phase).toBe("ended");
    expect(rooms().every((r) => r.disconnected)).toBe(true);
  });

  it("rejoins once with a fresh token when the room drops for good", async () => {
    const store = enabledStore();
    const live = aCall({ state: "active", answered_at: new Date().toISOString() });
    vi.spyOn(callService, "start").mockResolvedValue(joined(live));
    const join = vi.spyOn(callService, "join").mockResolvedValue(joined(live, "tok-2"));
    await store.start("conv1", "audio");
    rooms()[0].emit("disconnected");
    await flush();
    expect(join).toHaveBeenCalledWith("call1");
    expect(rooms()[1].connected?.token).toBe("tok-2");
    expect(store.phase).toBe("in_call");

    // A second loss gives up.
    rooms()[1].emit("disconnected");
    await flush();
    expect(store.phase).toBe("ended");
    expect(store.endReason).toBe("connection_lost");
  });

  it("shows reconnecting while LiveKit resumes", async () => {
    const store = enabledStore();
    vi.spyOn(callService, "start").mockResolvedValue(joined(aCall({ state: "active" })));
    await store.start("conv1", "audio");
    rooms()[0].emit("reconnecting");
    expect(store.reconnecting).toBe(true);
    rooms()[0].emit("reconnected");
    expect(store.reconnecting).toBe(false);
  });
});

describe("incoming call", () => {
  it("rings, accepts with a fresh token and reaches in_call", async () => {
    const store = enabledStore();
    store.onRinging(ring());
    expect(store.phase).toBe("incoming");
    expect(tones.start).toHaveBeenCalledWith("incoming", expect.anything());
    const live = aCall({ state: "active", initiator_id: PEER, answered_at: new Date().toISOString() });
    const join = vi.spyOn(callService, "join").mockResolvedValue(joined(live, "tok-b"));
    await store.accept();
    expect(join).toHaveBeenCalledWith("call1");
    expect(rooms()[0].connected?.token).toBe("tok-b");
    expect(store.phase).toBe("in_call");
    expect(store.incoming).toBeNull();
  });

  it("stops ringing when answered on another of my devices", () => {
    const store = enabledStore();
    store.onRinging(ring());
    store.onAnswered({ call_id: "call1", conversation_id: "conv1", account: ME });
    expect(store.phase).toBe("idle");
    expect(tones.stop).toHaveBeenCalled();
  });

  it("keeps ringing when someone else answers a group call", () => {
    const store = enabledStore();
    store.onRinging(ring({ conversation_type: "group" }));
    store.onAnswered({ call_id: "call1", conversation_id: "conv1", account: "someone" });
    expect(store.phase).toBe("incoming");
  });

  it("stops ringing when the call ends or I miss it", () => {
    const store = enabledStore();
    store.onRinging(ring());
    store.onMissed({ call_id: "call1", conversation_id: "conv1", final: false, missed: [ME] });
    expect(store.phase).toBe("idle");
    store.onRinging(ring({ call_id: "call2" }));
    store.onEnded({ call_id: "call2", conversation_id: "conv1", reason: "hangup", duration_s: 0 });
    expect(store.phase).toBe("idle");
  });

  it("declines and posts the decline", async () => {
    const store = enabledStore();
    const decline = vi.spyOn(callService, "decline").mockResolvedValue(aCall({ state: "ended" }));
    store.onRinging(ring());
    await store.decline();
    expect(decline).toHaveBeenCalledWith("call1");
    expect(store.phase).toBe("idle");
  });

  it("does not ring for my own call, or while I am already in one", async () => {
    const store = enabledStore();
    store.onRinging(ring({ initiator: ME }));
    expect(store.phase).toBe("idle");
    vi.spyOn(callService, "start").mockResolvedValue(joined(aCall({ state: "active" })));
    await store.start("conv1", "audio");
    store.onRinging(ring({ call_id: "other" }));
    expect(store.phase).toBe("in_call");
    expect(store.incoming).toBeNull();
  });

  it("a ring whose frames were lost stops on its own", () => {
    vi.useFakeTimers();
    const store = enabledStore();
    store.onRinging(ring({ expires_at: new Date(Date.now() + 1000).toISOString() }));
    vi.advanceTimersByTime(7000);
    expect(store.phase).toBe("idle");
  });

  it("opening a conversation with a call ringing for me shows the ring", async () => {
    const store = enabledStore();
    vi.spyOn(callService, "active").mockResolvedValue(
      aCall({
        initiator_id: PEER,
        participants: [
          { account_id: PEER, state: "accepted", in_room: true },
          { account_id: ME, state: "ringing", in_room: false },
        ],
      }),
    );
    await store.watchConversation("conv1");
    expect(store.phase).toBe("incoming");
    expect(store.active.conv1?.id).toBe("call1");
  });
});

describe("app-wide binding", () => {
  it("frames reach the store after bind, and nothing after reset", async () => {
    vi.spyOn(callService, "config").mockResolvedValue({ enabled: true, ring_timeout_s: 45, max_participants: 16 });
    vi.spyOn(callService, "active").mockResolvedValue(null);
    const store = useCallStore();
    store.bind();
    await flush();
    const emit = (frame: Record<string, unknown>) => (realtime as unknown as { emit(f: unknown): void }).emit(frame);
    emit(ring());
    expect(store.phase).toBe("incoming");

    const decline = vi.spyOn(callService, "decline").mockResolvedValue(aCall({ state: "ended" }));
    await store.reset();
    expect(decline).toHaveBeenCalledWith("call1");
    expect(store.phase).toBe("idle");
    expect(store.enabled).toBe(false);
    emit(ring({ call_id: "late" }));
    expect(store.phase).toBe("idle");
  });

  it("logout hangs up and releases the room", async () => {
    const store = enabledStore();
    vi.spyOn(callService, "start").mockResolvedValue(joined(aCall({ state: "active" })));
    const end = vi.spyOn(callService, "end").mockResolvedValue(aCall({ state: "ended" }));
    await store.start("conv1", "audio");
    await store.reset();
    expect(end).toHaveBeenCalledWith("call1");
    expect(rooms()[0].disconnected).toBe(true);
    expect(store.call).toBeNull();
  });
});

describe("media errors", () => {
  it.each([
    ["NotAllowedError", "mic", "calls.errors.micDenied"],
    ["NotFoundError", "mic", "calls.errors.noMic"],
    ["NotFoundError", "camera", "calls.errors.noCamera"],
    ["AbortError", "camera", "calls.errors.cameraFailed"],
  ] as const)("%s on the %s is %s", (name, device, key) => {
    expect(mediaErrorKey({ name }, device)).toBe(key);
  });
});

describe("call log messages", () => {
  it("parses the server's codes and nothing else", () => {
    expect(parseCallLog("call:missed:audio")).toEqual({ outcome: "missed", kind: "audio", seconds: 0 });
    expect(parseCallLog("call:ended:video:192")).toEqual({ outcome: "ended", kind: "video", seconds: 192 });
    expect(parseCallLog("call:declined:video")).toEqual({ outcome: "declined", kind: "video", seconds: 0 });
    expect(parseCallLog("call:ended:audio")).toBeNull();
    expect(parseCallLog("call:missed:fax")).toBeNull();
    expect(parseCallLog("<b>hi</b>")).toBeNull();
    expect(parseCallLog(null)).toBeNull();
  });

  it("formats durations", () => {
    expect(formatDuration(7)).toBe("0:07");
    expect(formatDuration(192)).toBe("3:12");
    expect(formatDuration(3723)).toBe("1:02:03");
  });

  it("words a missed call from each side", () => {
    const missed = parseCallLog("call:missed:video")!;
    expect(callLogKey(missed, false)).toBe("calls.log.missedVideo");
    expect(callLogKey(missed, true)).toBe("calls.log.noAnswer");
    expect(callLogKey(parseCallLog("call:ended:audio:5")!, true)).toBe("calls.log.voiceEnded");
  });
});
