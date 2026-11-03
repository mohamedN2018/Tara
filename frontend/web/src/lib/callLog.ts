// Call-log system messages. The server writes a short code as the body of a
// `type: "system"` message, sent by the call's initiator:
//   call:missed:<kind>   call:declined:<kind>   call:ended:<kind>:<seconds>
// Anything else is not a call log (an unknown system message).
import type { CallKind } from "@/services/calls";

export type CallLogOutcome = "missed" | "declined" | "ended";

export interface CallLog {
  outcome: CallLogOutcome;
  kind: CallKind;
  seconds: number;
}

const CODE = /^call:(missed|declined|ended):(audio|video)(?::(\d{1,7}))?$/;

export function parseCallLog(body: string | null | undefined): CallLog | null {
  const match = CODE.exec((body ?? "").trim());
  if (!match) return null;
  const outcome = match[1] as CallLogOutcome;
  if (outcome === "ended" && match[3] === undefined) return null;
  return { outcome, kind: match[2] as CallKind, seconds: match[3] ? Number(match[3]) : 0 };
}

/** "0:07", "3:12", "1:02:03". Digits stay Latin in both languages, like other times. */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** The i18n key for a call-log chip, from the viewer's side of the call. */
export function callLogKey(log: CallLog, viewerIsCaller: boolean): string {
  if (log.outcome === "ended") return log.kind === "video" ? "calls.log.videoEnded" : "calls.log.voiceEnded";
  if (log.outcome === "declined") return viewerIsCaller ? "calls.log.declinedByThem" : "calls.log.declinedByYou";
  if (viewerIsCaller) return "calls.log.noAnswer";
  return log.kind === "video" ? "calls.log.missedVideo" : "calls.log.missedVoice";
}
