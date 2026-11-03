import { afterEach, describe, expect, it, vi } from "vitest";

import { iconFor, notificationText, urlFor } from "@/components/notifications/kinds";
import { navItems } from "@/components/layout/navItems";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { formatRange, fromInputParts, safeHttpUrl, toInputParts, zoneDiffers } from "@/lib/eventTime";
import { EVENT_ERRORS, eventsService } from "@/services/events";
import type { Notification } from "@/types";

const g = i18n.global;

function row(over: Partial<Notification> = {}): Notification {
  return {
    id: "n1",
    kind: "gathering.invite",
    actor_id: "a1",
    actor_count: 1,
    subject_ref: "gathering:e1",
    body: "invited you to an event",
    read_at: null,
    created_at: "2026-11-01T10:00:00Z",
    last_event_at: "2026-11-01T10:00:00Z",
    url: "/events/e1",
    ...over,
  };
}

const text = (n: Notification, locale: "en" | "ar" = "en") => {
  g.locale.value = locale;
  return notificationText(n, g.t as never, g.te, "Sara");
};

afterEach(() => {
  g.locale.value = "en";
});

describe("event times", () => {
  it("round-trips the date and time inputs through an ISO instant", () => {
    const iso = fromInputParts("2026-12-24", "19:30");
    expect(iso).not.toBeNull();
    expect(toInputParts(iso)).toEqual({ date: "2026-12-24", time: "19:30" });
  });

  it.each([
    ["2026-02-31", "10:00"],
    ["2026-13-01", "10:00"],
    ["2026-12-01", "25:00"],
    ["", "10:00"],
    ["2026-12-01", ""],
    ["24/12/2026", "10:00"],
  ])("rejects %s %s", (date, time) => {
    expect(fromInputParts(date, time)).toBeNull();
  });

  it("formats a range in a given zone and locale", () => {
    const text = formatRange("2026-12-24T17:00:00Z", "2026-12-24T19:00:00Z", "en-GB", "UTC");
    expect(text).toContain("24 December 2026");
    expect(text).toContain("17:00");
    expect(text).toContain("19:00");
    expect(formatRange("2026-12-24T17:00:00Z", null, "ar", "UTC")).toContain("·");
  });

  it("only notes the host zone when the wall time differs", () => {
    expect(zoneDiffers("", "2026-12-24T17:00:00Z")).toBe(false);
    expect(zoneDiffers("Pacific/Kiritimati", "2026-12-24T17:00:00Z")).toBe(
      Intl.DateTimeFormat().resolvedOptions().timeZone !== "Pacific/Kiritimati",
    );
  });

  it.each([
    ["https://meet.example/x", "https://meet.example/x"],
    ["http://example.com", "http://example.com/"],
    ["javascript:alert(1)", null],
    ["data:text/html,hi", null],
    ["ftp://example.com", null],
    ["not a url", null],
    ["", null],
  ])("opens only http(s) links: %s", (url, expected) => {
    expect(safeHttpUrl(url)).toBe(expected);
  });
});

describe("event notifications", () => {
  it("words each kind in both languages", () => {
    expect(text(row())).toBe("Sara invited you to an event");
    expect(text(row({ kind: "gathering.cancel" }))).toBe("Sara cancelled an event you're going to");
    expect(text(row({ kind: "gathering.reminder", actor_id: null, data: { window: "24h" } }))).toContain("within a day");
    expect(text(row({ kind: "gathering.reminder", actor_id: null, data: { window: "1h" } }))).toContain("within the hour");
    expect(text(row({ kind: "gathering.rsvp", data: { status: "interested" } }))).toBe("Sara is interested in your event");
    expect(text(row({ kind: "gathering.rsvp", actor_count: 4 }))).toBe("Sara and 3 others responded to your event");
    expect(text(row(), "ar")).toBe("دعاك Sara إلى فعالية");
    expect(text(row({ kind: "gathering.rsvp", actor_count: 2 }), "ar")).toBe("ردّ Sara وشخص آخر على فعاليتك");
  });

  it("links to the event page, also for rows without a server url", () => {
    expect(urlFor(row())).toBe("/events/e1");
    expect(urlFor(row({ url: "" }))).toBe("/events/e1");
    expect(iconFor("gathering.reminder")).not.toBe(iconFor("unknown.kind"));
  });
});

describe("events service and nav", () => {
  it("has an Events item in the sidebar", () => {
    expect(navItems.find((i) => i.route === "/events")?.labelKey).toBe("nav.events");
    expect(g.t("nav.events")).toBe("Events");
  });

  it("asks for a tab with its cursor and search", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue({ data: { data: [], page: { next_cursor: null, prev_cursor: null, has_more: false } } });
    await eventsService.list("going", "abc", "book");
    expect(get).toHaveBeenCalledWith("/events/", { params: { scope: "going", cursor: "abc", q: "book" } });
    await eventsService.list("upcoming");
    expect(get).toHaveBeenLastCalledWith("/events/", { params: { scope: "upcoming" } });
  });

  it("sends invites and RSVPs to the event's endpoints", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue({ data: { data: { invited: ["f1"] } } });
    expect(await eventsService.invite("e1", ["f1"])).toEqual(["f1"]);
    expect(post).toHaveBeenCalledWith("/events/e1/invite/", { account_ids: ["f1"] });
    await eventsService.rsvp("e1", "going");
    expect(post).toHaveBeenLastCalledWith("/events/e1/rsvp/", { status: "going" });
    await eventsService.report("e1", "spam");
    expect(post).toHaveBeenLastCalledWith("/events/e1/report/", { reason: "spam" });
  });

  it("explains a full event in the viewer's language", () => {
    const full = { response: { status: 409, data: { error: { code: "event_full", message: "The event is full." } } } };
    expect(errorMessage(full, EVENT_ERRORS)).toBe("This event is full.");
    g.locale.value = "ar";
    expect(errorMessage(full, EVENT_ERRORS)).toBe("اكتمل عدد الحضور في هذه الفعالية.");
  });

  it("pluralises counts in Arabic", () => {
    g.locale.value = "ar";
    expect(g.t("events.counts.going", { count: 2 }, 2)).toBe("سيحضر شخصان");
    expect(g.t("events.counts.going", { count: 5 }, 5)).toBe("سيحضر 5 أشخاص");
    expect(g.t("events.counts.spotsLeft", { count: 11 }, 11)).toBe("بقي 11 مكانًا");
    g.locale.value = "en";
    expect(g.t("events.counts.spotsLeft", { count: 1 }, 1)).toBe("1 spot left");
    expect(g.t("events.inviteSend", { count: 3 }, 3)).toBe("Invite 3 friends");
  });
});
