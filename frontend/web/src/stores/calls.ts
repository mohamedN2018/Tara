// Voice and video calls on LiveKit: one call at a time per browser tab.
//
// Phases:   idle ─start─> outgoing ─answered─> in_call ─hang up / ended─> ended ─> idle
//           idle ─ring──> incoming ─accept───> connecting ─> in_call
//           idle ─rejoin─────────────────────> connecting ─> in_call
// `reconnecting` is a sub-state of a connected phase (LiveKit is resuming).
//
// The server owns the call: realtime frames (`call.*`) and REST answers move
// the phase, never a guess. Every (re)connect gets a fresh token from the API.
// Every track, room listener, timer and tone is released on hang-up, on
// `call.ended`, on a lost connection and on logout (`reset`).
import type { Participant, Room, Track as LkTrack } from "livekit-client";
import { defineStore } from "pinia";
import { computed, markRaw, ref, shallowRef } from "vue";

import { apiError } from "@/lib/api";
import { startTone, stopTone } from "@/lib/ringtone";
import { realtime } from "@/lib/ws";
import {
  type Call,
  type CallConfig,
  type CallJoin,
  type CallKind,
  callService,
  DISABLED_CONFIG,
} from "@/services/calls";
import { useAuthStore } from "@/stores/auth";
import { useNotificationStore } from "@/stores/notifications";

export type CallPhase = "idle" | "outgoing" | "incoming" | "connecting" | "in_call" | "ended";

/** Why the call screen closed; each has a `calls.end.<reason>` string. */
export type EndReason =
  | "ended"
  | "declined"
  | "no_answer"
  | "connection_lost"
  | "failed"
  | "full"
  | "unavailable"
  | "not_found";

export interface IncomingRing {
  call_id: string;
  conversation_id: string;
  conversation_type: string;
  kind: CallKind;
  initiator: string;
  expires_at: string | null;
}

export interface CallTile {
  key: string;
  identity: string;
  local: boolean;
  video: LkTrack | null;
  screen: boolean;
  micMuted: boolean;
  speaking: boolean;
}

// The LiveKit SDK is large: it loads with the first call, not with the app.
type LiveKit = typeof import("livekit-client");
let sdk: LiveKit | null = null;
async function liveKit(): Promise<LiveKit> {
  sdk ??= await import("livekit-client");
  return sdk;
}

export const MAX_TILES = 9;
const ENDED_SCREEN_MS = 2500;
const RING_GRACE_MS = 5000;

type Frame = Record<string, unknown>;

/** A media error as one of our notice keys. */
export function mediaErrorKey(error: unknown, device: "mic" | "camera"): string {
  const name = (error as { name?: string } | null)?.name ?? "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") {
    return device === "mic" ? "calls.errors.micDenied" : "calls.errors.cameraDenied";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError") {
    return device === "mic" ? "calls.errors.noMic" : "calls.errors.noCamera";
  }
  return device === "mic" ? "calls.errors.micFailed" : "calls.errors.cameraFailed";
}

const END_CODES: Record<string, EndReason> = {
  calls_unavailable: "unavailable",
  call_full: "full",
  call_ended: "ended",
  not_found: "not_found",
};

export const useCallStore = defineStore("calls", () => {
  const config = ref<CallConfig>({ ...DISABLED_CONFIG });
  const phase = ref<CallPhase>("idle");
  const call = ref<Call | null>(null);
  const incoming = ref<IncomingRing | null>(null);
  const endReason = ref<EndReason | null>(null);
  const notice = ref<string | null>(null);
  const reconnecting = ref(false);
  const minimised = ref(false);
  const micOn = ref(false);
  const camOn = ref(false);
  const screenOn = ref(false);
  const audioBlocked = ref(false);
  const tiles = shallowRef<CallTile[]>([]);
  const remoteAudio = shallowRef<{ key: string; track: LkTrack }[]>([]);
  const activeSpeaker = ref<string | null>(null);
  const cameras = shallowRef<MediaDeviceInfo[]>([]);
  const outputs = shallowRef<MediaDeviceInfo[]>([]);
  const outputId = ref<string>("");
  const connectedAt = ref<number | null>(null);
  const now = ref(Date.now());
  /** Live calls by conversation, for the rejoin banner. */
  const active = ref<Record<string, Call>>({});

  let room: Room | null = null;
  let leaving = false;
  let rejoinTried = false;
  let frameUnsubs: Array<() => void> = [];
  let ticker: number | null = null;
  let ringTimer: number | null = null;
  let endedTimer: number | null = null;
  let generation = 0; // bumps on every teardown: late async results are dropped

  const me = () => useAuthStore().account?.id ?? "";
  const quiet = () => {
    try {
      return useNotificationStore().quietHours;
    } catch {
      return null;
    }
  };

  const enabled = computed(() => config.value.enabled);
  const busy = computed(() => phase.value !== "idle" && phase.value !== "ended");
  const duration = computed(() =>
    connectedAt.value ? Math.max(0, Math.floor((now.value - connectedAt.value) / 1000)) : 0,
  );
  const isCaller = computed(() => !!call.value && call.value.initiator_id === me());
  const kind = computed<CallKind>(() => call.value?.kind ?? incoming.value?.kind ?? "audio");
  const isGroup = computed(() => (call.value?.conversation_type ?? incoming.value?.conversation_type) === "group");
  const canScreenShare = computed(
    () =>
      typeof navigator !== "undefined" &&
      !!navigator.mediaDevices &&
      "getDisplayMedia" in navigator.mediaDevices &&
      !(typeof window !== "undefined" && window.matchMedia?.("(pointer: coarse)").matches),
  );
  const canPickOutput = computed(
    () => typeof HTMLMediaElement !== "undefined" && "setSinkId" in HTMLMediaElement.prototype && outputs.value.length > 1,
  );
  /** A screen share, or in a group the active speaker; null shows a plain grid. */
  const spotlight = computed<CallTile | null>(() => {
    const shared = tiles.value.find((t) => t.screen);
    if (shared) return shared;
    if (tiles.value.length <= 2 || !activeSpeaker.value) return null;
    return tiles.value.find((t) => !t.screen && !t.local && t.identity === activeSpeaker.value) ?? null;
  });
  /** At most nine tiles: the spotlight first, then remote people, then me. */
  const visibleTiles = computed(() => {
    const ordered = [...tiles.value].sort((a, b) => Number(a.local) - Number(b.local));
    const first = spotlight.value;
    const rest = first ? ordered.filter((t) => t.key !== first.key) : ordered;
    return (first ? [first, ...rest] : rest).slice(0, MAX_TILES);
  });

  // ---- timers -----------------------------------------------------------------

  function clearTimer(id: number | null, interval = false) {
    if (id === null) return;
    if (interval) window.clearInterval(id);
    else window.clearTimeout(id);
  }

  function startTicker() {
    clearTimer(ticker, true);
    now.value = Date.now();
    ticker = window.setInterval(() => (now.value = Date.now()), 1000);
  }

  // ---- media -------------------------------------------------------------------

  function refreshTiles() {
    const r = room;
    if (!r || !sdk) {
      tiles.value = [];
      remoteAudio.value = [];
      return;
    }
    const { Track } = sdk;
    const people: Participant[] = [r.localParticipant, ...Array.from(r.remoteParticipants.values())];
    const next: CallTile[] = [];
    const audio: { key: string; track: LkTrack }[] = [];
    for (const p of people) {
      const local = p === r.localParticipant;
      const cam = p.getTrackPublication(Track.Source.Camera);
      const mic = p.getTrackPublication(Track.Source.Microphone);
      const screen = p.getTrackPublication(Track.Source.ScreenShare);
      next.push({
        key: `${p.identity}:camera`,
        identity: p.identity,
        local,
        video: cam?.track && !cam.isMuted ? markRaw(cam.track) : null,
        screen: false,
        micMuted: !mic || mic.isMuted,
        speaking: p.isSpeaking,
      });
      if (screen?.track) {
        next.push({
          key: `${p.identity}:screen`,
          identity: p.identity,
          local,
          video: markRaw(screen.track),
          screen: true,
          micMuted: true,
          speaking: false,
        });
      }
      if (!local) {
        for (const pub of p.audioTrackPublications.values()) {
          if (pub.track) audio.push({ key: `${p.identity}:${pub.trackSid}`, track: markRaw(pub.track) });
        }
      }
    }
    tiles.value = next;
    remoteAudio.value = audio;
    micOn.value = r.localParticipant.isMicrophoneEnabled;
    camOn.value = r.localParticipant.isCameraEnabled;
    screenOn.value = r.localParticipant.isScreenShareEnabled;
  }

  async function loadDevices() {
    try {
      const { Room } = await liveKit();
      cameras.value = await Room.getLocalDevices("videoinput", false);
      outputs.value = await Room.getLocalDevices("audiooutput", false);
    } catch {
      cameras.value = [];
      outputs.value = [];
    }
  }

  async function publishLocal(r: Room, wantVideo: boolean) {
    try {
      await r.localParticipant.setMicrophoneEnabled(true);
    } catch (error) {
      notice.value = mediaErrorKey(error, "mic");
    }
    if (wantVideo) {
      try {
        await r.localParticipant.setCameraEnabled(true);
      } catch (error) {
        // A video call without a camera carries on as a voice call.
        notice.value = `${mediaErrorKey(error, "camera")}Fallback`;
      }
    }
    refreshTiles();
    void loadDevices();
  }

  function listen(r: Room, RoomEvent: LiveKit["RoomEvent"]) {
    const refresh = () => refreshTiles();
    r.on(RoomEvent.ParticipantConnected, refresh)
      .on(RoomEvent.ParticipantDisconnected, refresh)
      .on(RoomEvent.TrackSubscribed, refresh)
      .on(RoomEvent.TrackUnsubscribed, refresh)
      .on(RoomEvent.TrackMuted, refresh)
      .on(RoomEvent.TrackUnmuted, refresh)
      .on(RoomEvent.LocalTrackPublished, refresh)
      .on(RoomEvent.LocalTrackUnpublished, refresh)
      .on(RoomEvent.ActiveSpeakersChanged, (speakers: Participant[]) => {
        activeSpeaker.value = speakers.find((s) => s !== r.localParticipant)?.identity ?? null;
        refreshTiles();
      })
      .on(RoomEvent.Reconnecting, () => (reconnecting.value = true))
      .on(RoomEvent.Reconnected, () => {
        reconnecting.value = false;
        refreshTiles();
      })
      .on(RoomEvent.AudioPlaybackStatusChanged, () => (audioBlocked.value = !r.canPlaybackAudio))
      .on(RoomEvent.MediaDevicesChanged, () => void loadDevices())
      .on(RoomEvent.MediaDevicesError, (error: Error) => (notice.value = mediaErrorKey(error, "mic")))
      .on(RoomEvent.Disconnected, () => {
        if (room !== r || leaving) return;
        void onLostConnection();
      });
  }

  async function connect(join: CallJoin, wantVideo: boolean): Promise<void> {
    const mine = generation;
    const { Room, RoomEvent } = await liveKit();
    if (mine !== generation) return;
    const r = new Room({ adaptiveStream: true, dynacast: true });
    room = r;
    listen(r, RoomEvent);
    await r.connect(join.url, join.token);
    if (mine !== generation || room !== r) {
      // Hung up while connecting.
      await r.disconnect();
      return;
    }
    audioBlocked.value = !r.canPlaybackAudio;
    await publishLocal(r, wantVideo);
  }

  /** The room dropped for good (LiveKit gave up resuming): rejoin once with a fresh token. */
  async function onLostConnection() {
    const current = call.value;
    if (!current || rejoinTried || !busy.value) {
      finish("connection_lost");
      return;
    }
    rejoinTried = true;
    reconnecting.value = true;
    const old = room;
    room = null;
    old?.removeAllListeners();
    try {
      const join = await callService.join(current.id);
      if (call.value?.id !== current.id) return;
      call.value = join.call;
      await connect(join, camOn.value);
      reconnecting.value = false;
    } catch {
      finish("connection_lost");
    }
  }

  async function releaseRoom() {
    const r = room;
    room = null;
    leaving = true;
    if (r) {
      r.removeAllListeners();
      try {
        await r.disconnect(true); // also stops every local track
      } catch {
        // Already gone.
      }
    }
    leaving = false;
  }

  /** Release everything this tab holds for the call. Leaves `phase` to the caller. */
  function teardown() {
    generation += 1;
    stopTone();
    clearTimer(ticker, true);
    clearTimer(ringTimer);
    ticker = ringTimer = null;
    void releaseRoom();
    tiles.value = [];
    remoteAudio.value = [];
    activeSpeaker.value = null;
    micOn.value = camOn.value = screenOn.value = false;
    reconnecting.value = false;
    audioBlocked.value = false;
    connectedAt.value = null;
    minimised.value = false;
    rejoinTried = false;
  }

  function toIdle() {
    clearTimer(endedTimer);
    endedTimer = null;
    phase.value = "idle";
    call.value = null;
    incoming.value = null;
    endReason.value = null;
    notice.value = null;
  }

  /** Close the call screen with a reason, then go idle. */
  function finish(reason: EndReason) {
    teardown();
    incoming.value = null;
    phase.value = "ended";
    endReason.value = reason;
    clearTimer(endedTimer);
    endedTimer = window.setTimeout(toIdle, ENDED_SCREEN_MS);
  }

  function enterCall(answeredAt?: string | null) {
    stopTone();
    phase.value = "in_call";
    const answered = answeredAt ? Date.parse(answeredAt) : NaN;
    connectedAt.value = Number.isFinite(answered) ? Math.min(answered, Date.now()) : Date.now();
    startTicker();
  }

  function failWith(error: unknown) {
    const code = apiError(error).code;
    if (code === "calls_unavailable") config.value = { ...config.value, enabled: false };
    finish(END_CODES[code] ?? "failed");
  }

  function remember(c: Call | null) {
    if (!c) return;
    if (c.state === "ringing" || c.state === "active") active.value = { ...active.value, [c.conversation_id]: c };
    else forget(c.conversation_id, c.id);
  }

  function forget(conversationId: string, callId?: string) {
    const known = active.value[conversationId];
    if (!known || (callId && known.id !== callId)) return;
    const next = { ...active.value };
    delete next[conversationId];
    active.value = next;
  }

  // ---- actions ------------------------------------------------------------------

  async function loadConfig() {
    try {
      config.value = await callService.config();
    } catch {
      config.value = { ...DISABLED_CONFIG };
    }
  }

  async function start(conversationId: string, callKind: CallKind) {
    if (!enabled.value || busy.value) return;
    toIdle();
    const mine = generation;
    phase.value = "connecting";
    notice.value = null;
    try {
      const join = await callService.start(conversationId, callKind);
      if (mine !== generation) return;
      call.value = join.call;
      remember(join.call);
      const ringing = join.call.state === "ringing" && join.call.initiator_id === me();
      if (ringing) {
        phase.value = "outgoing";
        startTone("outgoing", quiet());
      }
      await connect(join, callKind === "video" || join.call.kind === "video");
      if (mine !== generation) return;
      if (!ringing && phase.value === "connecting") enterCall(join.call.answered_at);
    } catch (error) {
      if (mine === generation) failWith(error);
    }
  }

  async function accept() {
    const ring = incoming.value;
    if (!ring || phase.value !== "incoming") return;
    stopTone();
    clearTimer(ringTimer);
    ringTimer = null;
    const mine = generation;
    phase.value = "connecting";
    try {
      const join = await callService.join(ring.call_id);
      if (mine !== generation) return;
      incoming.value = null;
      call.value = join.call;
      remember(join.call);
      await connect(join, ring.kind === "video");
      if (mine !== generation) return;
      enterCall(join.call.answered_at);
    } catch (error) {
      if (mine === generation) failWith(error);
    }
  }

  async function decline() {
    const ring = incoming.value;
    if (!ring) return;
    stopTone();
    clearTimer(ringTimer);
    ringTimer = null;
    toIdle();
    try {
      await callService.decline(ring.call_id);
    } catch {
      // The call may already be over; nothing to undo here.
    }
  }

  /** Join the conversation's live call from the banner (or a ring found on load). */
  async function rejoin(callId: string) {
    if (!enabled.value || busy.value) return;
    toIdle();
    const mine = generation;
    phase.value = "connecting";
    try {
      const join = await callService.join(callId);
      if (mine !== generation) return;
      call.value = join.call;
      remember(join.call);
      const stillRinging = join.call.state === "ringing" && join.call.initiator_id === me();
      await connect(join, join.call.kind === "video");
      if (mine !== generation) return;
      if (stillRinging) phase.value = "outgoing";
      else enterCall(join.call.answered_at);
    } catch (error) {
      if (mine === generation) failWith(error);
    }
  }

  async function hangup() {
    const current = call.value;
    finish("ended");
    if (!current) return;
    try {
      const after = await callService.end(current.id);
      remember(after);
    } catch {
      // Ended already, or offline: the server's sweeper and webhooks settle it.
    }
  }

  async function toggleMic() {
    if (!room) return;
    try {
      await room.localParticipant.setMicrophoneEnabled(!micOn.value);
    } catch (error) {
      notice.value = mediaErrorKey(error, "mic");
    }
    refreshTiles();
  }

  async function toggleCamera() {
    if (!room) return;
    try {
      await room.localParticipant.setCameraEnabled(!camOn.value);
    } catch (error) {
      notice.value = mediaErrorKey(error, "camera");
    }
    refreshTiles();
    void loadDevices();
  }

  async function switchCamera() {
    if (!room || cameras.value.length < 2) return;
    const current = room.getActiveDevice("videoinput");
    const index = cameras.value.findIndex((d) => d.deviceId === current);
    const next = cameras.value[(index + 1) % cameras.value.length];
    try {
      await room.switchActiveDevice("videoinput", next.deviceId);
    } catch (error) {
      notice.value = mediaErrorKey(error, "camera");
    }
  }

  async function setOutput(deviceId: string) {
    if (!room) return;
    try {
      await room.switchActiveDevice("audiooutput", deviceId);
      outputId.value = deviceId;
    } catch {
      notice.value = "calls.errors.outputFailed";
    }
  }

  async function toggleScreenShare() {
    if (!room || !canScreenShare.value) return;
    try {
      await room.localParticipant.setScreenShareEnabled(!screenOn.value, { audio: false });
    } catch (error) {
      // Closing the browser's picker is a NotAllowedError too: not worth a notice.
      if ((error as { name?: string })?.name !== "NotAllowedError") notice.value = "calls.errors.screenFailed";
    }
    refreshTiles();
  }

  async function enableAudio() {
    try {
      await room?.startAudio();
      audioBlocked.value = false;
    } catch {
      audioBlocked.value = true;
    }
  }

  // ---- realtime frames ------------------------------------------------------------

  function dismissRing(callId: string) {
    if (incoming.value?.call_id !== callId) return;
    stopTone();
    clearTimer(ringTimer);
    ringTimer = null;
    if (phase.value === "incoming") toIdle();
    else incoming.value = null;
  }

  function showRing(ring: IncomingRing) {
    if (!enabled.value || ring.initiator === me()) return;
    // Already in (or placing) a call here: the other call rings out unanswered.
    if (busy.value) return;
    toIdle();
    incoming.value = ring;
    phase.value = "incoming";
    minimised.value = false;
    startTone("incoming", quiet());
    const expires = ring.expires_at ? Date.parse(ring.expires_at) : NaN;
    const wait = Number.isFinite(expires)
      ? Math.max(0, expires - Date.now()) + RING_GRACE_MS
      : config.value.ring_timeout_s * 1000 + RING_GRACE_MS;
    clearTimer(ringTimer);
    // The server's sweeper decides "missed"; this only stops a ring whose frame was lost.
    ringTimer = window.setTimeout(() => dismissRing(ring.call_id), wait);
  }

  async function refreshActive(conversationId: string) {
    if (!enabled.value || !conversationId) return null;
    try {
      const live = await callService.active(conversationId);
      if (live) remember(live);
      else forget(conversationId);
      return live;
    } catch {
      return null;
    }
  }

  /** Opened a conversation: learn its live call, and ring if it is ringing for me. */
  async function watchConversation(conversationId: string) {
    const live = await refreshActive(conversationId);
    if (!live || live.state !== "ringing" || busy.value) return;
    const mineRinging = live.participants.some((p) => p.account_id === me() && p.state === "ringing");
    if (mineRinging) {
      showRing({
        call_id: live.id,
        conversation_id: live.conversation_id,
        conversation_type: live.conversation_type,
        kind: live.kind,
        initiator: live.initiator_id,
        expires_at: live.ring_expires_at,
      });
    }
  }

  const str = (v: unknown) => (typeof v === "string" ? v : "");

  function onRinging(f: Frame) {
    const ring: IncomingRing = {
      call_id: str(f.call_id),
      conversation_id: str(f.conversation_id),
      conversation_type: str(f.conversation_type) || "dm",
      kind: f.kind === "video" ? "video" : "audio",
      initiator: str(f.initiator),
      expires_at: str(f.expires_at) || null,
    };
    if (!ring.call_id) return;
    void refreshActive(ring.conversation_id);
    showRing(ring);
  }

  function onAnswered(f: Frame) {
    const callId = str(f.call_id);
    const account = str(f.account);
    void refreshActive(str(f.conversation_id));
    // Answered on another of my devices: stop ringing here.
    if (account === me()) dismissRing(callId);
    if (call.value?.id === callId && isCaller.value && phase.value === "outgoing") {
      call.value = { ...call.value, state: "active", answered_at: new Date().toISOString() };
      enterCall();
    }
  }

  function onDeclined(f: Frame) {
    const callId = str(f.call_id);
    if (str(f.account) === me()) dismissRing(callId);
    if (call.value?.id === callId) {
      call.value = {
        ...call.value,
        participants: call.value.participants.map((p) =>
          p.account_id === str(f.account) ? { ...p, state: "declined" } : p,
        ),
      };
    }
  }

  function onEnded(f: Frame) {
    const callId = str(f.call_id);
    forget(str(f.conversation_id), callId);
    dismissRing(callId);
    if (call.value?.id === callId && phase.value !== "ended") {
      finish(f.reason === "declined" ? "declined" : "ended");
    }
  }

  function onMissed(f: Frame) {
    const callId = str(f.call_id);
    const missed = Array.isArray(f.missed) ? (f.missed as unknown[]).map(String) : [];
    if (missed.includes(me())) dismissRing(callId);
    if (f.final) {
      forget(str(f.conversation_id), callId);
      dismissRing(callId);
      if (call.value?.id === callId && phase.value !== "ended") finish(isCaller.value ? "no_answer" : "ended");
    }
  }

  function onUpdated(f: Frame) {
    void refreshActive(str(f.conversation_id));
  }

  /** Frames sent while the socket was down are gone: re-check what we show. */
  async function onReconnected() {
    const current = call.value;
    if (current && busy.value) {
      const live = await refreshActive(current.conversation_id);
      if (!live || live.id !== current.id) finish("ended");
    }
    const ring = incoming.value;
    if (ring) {
      const live = await refreshActive(ring.conversation_id);
      if (!live || live.id !== ring.call_id || live.state !== "ringing") dismissRing(ring.call_id);
    }
  }

  /** The service worker forwards call pushes to open windows (sw.js): a backup for a down socket. */
  function onWorkerMessage(event: MessageEvent<unknown>) {
    const data = event.data as Frame | null;
    if (!data || data.type !== "tara.call") return;
    const conversationId = str(data.conversation_id);
    if (data.kind === "call.ring" && conversationId) void watchConversation(conversationId);
    else if (data.kind === "call.clear" || data.kind === "call.missed") {
      dismissRing(str(data.call_id));
      if (conversationId) void refreshActive(conversationId);
    }
  }

  function bind() {
    if (frameUnsubs.length) return;
    frameUnsubs = [
      realtime.on("call.ringing", onRinging),
      realtime.on("call.updated", onUpdated),
      realtime.on("call.answered", onAnswered),
      realtime.on("call.declined", onDeclined),
      realtime.on("call.ended", onEnded),
      realtime.on("call.missed", onMissed),
      realtime.on("_reconnected", () => void onReconnected()),
    ];
    if (typeof navigator !== "undefined" && navigator.serviceWorker) {
      navigator.serviceWorker.addEventListener("message", onWorkerMessage);
      frameUnsubs.push(() => navigator.serviceWorker.removeEventListener("message", onWorkerMessage));
    }
    void loadConfig();
  }

  /** Logout: hang up (best effort) and drop every listener, track and timer. */
  async function reset() {
    const current = call.value;
    const ring = incoming.value;
    teardown();
    toIdle();
    frameUnsubs.forEach((u) => u());
    frameUnsubs = [];
    active.value = {};
    config.value = { ...DISABLED_CONFIG };
    try {
      if (current) await callService.end(current.id);
      else if (ring) await callService.decline(ring.call_id);
    } catch {
      // The session may already be gone.
    }
  }

  return {
    config,
    phase,
    call,
    incoming,
    endReason,
    notice,
    reconnecting,
    minimised,
    micOn,
    camOn,
    screenOn,
    audioBlocked,
    tiles,
    remoteAudio,
    activeSpeaker,
    cameras,
    outputs,
    outputId,
    active,
    enabled,
    busy,
    duration,
    isCaller,
    kind,
    isGroup,
    canScreenShare,
    canPickOutput,
    spotlight,
    visibleTiles,
    loadConfig,
    start,
    accept,
    decline,
    rejoin,
    hangup,
    toggleMic,
    toggleCamera,
    switchCamera,
    setOutput,
    toggleScreenShare,
    enableAudio,
    refreshActive,
    watchConversation,
    bind,
    reset,
    dismiss: toIdle,
    // Exposed for tests and the overlay.
    onRinging,
    onAnswered,
    onDeclined,
    onEnded,
    onMissed,
  };
});
