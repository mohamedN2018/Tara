import { api } from "@/lib/api";
import type { CursorPage } from "@/types";

// Events (the post service's `gatherings` app, roadmap 1.13). The server owns
// every rule: visibility (a hidden event is a 404), capacity (409 event_full),
// host-only edits and friends-only invites.

export type EventAudience = "public" | "friends" | "invite_only";
export type EventStatus = "scheduled" | "cancelled" | "ended";
export type RsvpStatus = "going" | "interested" | "not_going";
export type LocationType = "place" | "online";
export type EventScope = "upcoming" | "hosting" | "going" | "invited" | "past";
export type AttendeeState = RsvpStatus | "invited";
export type ReportReason =
  | "spam"
  | "scam"
  | "hate"
  | "violence"
  | "nudity"
  | "harassment"
  | "false_information"
  | "other";

export const EVENT_SCOPES: EventScope[] = ["upcoming", "hosting", "going", "invited", "past"];
export const EVENT_AUDIENCES: EventAudience[] = ["public", "friends", "invite_only"];
export const RSVP_STATES: RsvpStatus[] = ["going", "interested", "not_going"];
export const REPORT_REASONS: ReportReason[] = [
  "spam",
  "scam",
  "hate",
  "violence",
  "nudity",
  "harassment",
  "false_information",
  "other",
];
export const MAX_TITLE = 120;
export const MAX_DESCRIPTION = 5000;
export const MAX_INVITES = 50;

export interface TaraEvent {
  id: string;
  host_id: string;
  host_type: string;
  page_id: string | null;
  title: string;
  description: string;
  starts_at: string;
  ends_at: string | null;
  /** The host's IANA time zone (the viewer sees times in their own). */
  timezone: string;
  location_type: LocationType;
  location: string;
  online_url: string;
  cover_media_id: string | null;
  audience: EventAudience;
  capacity: number | null;
  going_count: number;
  interested_count: number;
  spots_left: number | null;
  status: EventStatus;
  cancelled_at: string | null;
  is_host: boolean;
  my_rsvp: RsvpStatus | null;
  invited: boolean;
  created_at: string;
  updated_at: string;
}

export interface EventInput {
  title: string;
  description: string;
  starts_at: string;
  ends_at: string | null;
  timezone: string;
  location_type: LocationType;
  location: string;
  online_url: string;
  cover_media_id: string | null;
  audience: EventAudience;
  capacity: number | null;
}

export interface Attendee {
  account_id: string;
  status?: RsvpStatus;
  updated_at?: string;
  created_at?: string;
}

/** Event error codes with their own message (`events.errors.<code>`). */
export const EVENT_ERRORS: Record<string, string> = Object.fromEntries(
  [
    "event_full",
    "event_cancelled",
    "event_ended",
    "host_cannot_rsvp",
    "invite_not_friend",
    "invalid_url",
    "invalid_timezone",
    "starts_in_past",
    "starts_too_far",
    "ends_before_start",
    "location_required",
    "online_url_required",
    "capacity_below_going",
    "media_already_attached",
  ].map((code) => [code, `events.errors.${code}`]),
);

export const eventsService = {
  async list(scope: EventScope, cursor?: string | null, q = ""): Promise<CursorPage<TaraEvent>> {
    const { data } = await api.get<CursorPage<TaraEvent>>("/events/", {
      params: { scope, ...(cursor ? { cursor } : {}), ...(q ? { q } : {}) },
    });
    return data;
  },

  async get(id: string): Promise<TaraEvent> {
    const { data } = await api.get<{ data: TaraEvent }>(`/events/${id}/`);
    return data.data;
  },

  async create(input: EventInput): Promise<TaraEvent> {
    const { data } = await api.post<{ data: TaraEvent }>("/events/", input);
    return data.data;
  },

  async update(id: string, changes: Partial<EventInput>): Promise<TaraEvent> {
    const { data } = await api.patch<{ data: TaraEvent }>(`/events/${id}/`, changes);
    return data.data;
  },

  async cancel(id: string): Promise<TaraEvent> {
    const { data } = await api.post<{ data: TaraEvent }>(`/events/${id}/cancel/`);
    return data.data;
  },

  async remove(id: string): Promise<void> {
    await api.delete(`/events/${id}/`);
  },

  async rsvp(id: string, status: RsvpStatus): Promise<TaraEvent> {
    const { data } = await api.post<{ data: TaraEvent }>(`/events/${id}/rsvp/`, { status });
    return data.data;
  },

  async withdraw(id: string): Promise<TaraEvent> {
    const { data } = await api.delete<{ data: TaraEvent }>(`/events/${id}/rsvp/`);
    return data.data;
  },

  async attendees(id: string, status: AttendeeState, cursor?: string | null): Promise<CursorPage<Attendee>> {
    const { data } = await api.get<CursorPage<Attendee>>(`/events/${id}/attendees/`, {
      params: { status, ...(cursor ? { cursor } : {}) },
    });
    return data;
  },

  async invite(id: string, accountIds: string[]): Promise<string[]> {
    const { data } = await api.post<{ data: { invited: string[] } }>(`/events/${id}/invite/`, {
      account_ids: accountIds,
    });
    return data.data.invited;
  },

  async report(id: string, reason: ReportReason): Promise<void> {
    await api.post(`/events/${id}/report/`, { reason });
  },
};
