// Voice and video calls (chat service, LiveKit). The server picks the room and
// signs a short-lived token (<= 10 min) for it: the client never names a room,
// and a token is never reused, every (re)connect asks /join/ for a fresh one.
import { api } from "@/lib/api";

export type CallKind = "audio" | "video";
export type CallState = "ringing" | "active" | "ended" | "missed";
export type ParticipantState = "ringing" | "accepted" | "declined" | "missed" | "left";

export interface CallParticipant {
  account_id: string;
  state: ParticipantState;
  in_room: boolean;
}

export interface Call {
  id: string;
  conversation_id: string;
  conversation_type: string;
  kind: CallKind;
  state: CallState;
  initiator_id: string;
  created_at: string;
  answered_at: string | null;
  ended_at: string | null;
  end_reason: string;
  duration_s: number;
  ring_expires_at: string | null;
  participants: CallParticipant[];
}

export interface CallJoin {
  call_id: string;
  room: string;
  token: string;
  url: string;
  call: Call;
}

export interface CallConfig {
  enabled: boolean;
  ring_timeout_s: number;
  max_participants: number;
}

export const DISABLED_CONFIG: CallConfig = { enabled: false, ring_timeout_s: 45, max_participants: 16 };

export const callService = {
  async config(): Promise<CallConfig> {
    const { data } = await api.get<{ data: CallConfig }>("/calls/config/");
    return { ...DISABLED_CONFIG, ...data.data };
  },

  /** Start a call, or join the conversation's live one (201 new, 200 joined). */
  async start(conversationId: string, kind: CallKind): Promise<CallJoin> {
    const { data } = await api.post<{ data: CallJoin }>(`/conversations/${conversationId}/calls/`, { kind });
    return data.data;
  },

  /** Accept a ringing call or rejoin a live one: always a fresh token. */
  async join(callId: string): Promise<CallJoin> {
    const { data } = await api.post<{ data: CallJoin }>(`/calls/${callId}/join/`);
    return data.data;
  },

  async decline(callId: string): Promise<Call> {
    const { data } = await api.post<{ data: Call }>(`/calls/${callId}/decline/`);
    return data.data;
  },

  async end(callId: string): Promise<Call> {
    const { data } = await api.post<{ data: Call }>(`/calls/${callId}/end/`);
    return data.data;
  },

  async active(conversationId: string): Promise<Call | null> {
    const { data } = await api.get<{ data: Call | null }>(`/conversations/${conversationId}/calls/active/`);
    return data.data ?? null;
  },
};
