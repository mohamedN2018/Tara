import { api } from "@/lib/api";

/** A friend's birthday as identity shares it: day and month, never the year. */
export interface FriendBirthday {
  account_id: string;
  month: number;
  day: number;
  /** 0 = today. */
  days_until: number;
}

/** The viewer's local date as YYYY-MM-DD (identity's "today" follows it). */
export function localDate(d: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function splitBirthdays(rows: FriendBirthday[]): { today: FriendBirthday[]; upcoming: FriendBirthday[] } {
  return {
    today: rows.filter((r) => r.days_until === 0),
    upcoming: rows.filter((r) => r.days_until > 0),
  };
}

/** "5 November" / "٥ نوفمبر": day and month only, in the UI's language. */
export function birthdayDate(b: Pick<FriendBirthday, "month" | "day">, locale: string): string {
  // A leap year, so 29 February formats; noon UTC keeps the day in every zone.
  const when = new Date(Date.UTC(2000, b.month - 1, b.day, 12));
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "long", timeZone: "UTC" }).format(when);
}

/** The weekday the birthday falls on this time (for "This week" rows). */
export function birthdayWeekday(daysUntil: number, locale: string, today: Date = new Date()): string {
  const when = new Date(today.getFullYear(), today.getMonth(), today.getDate() + daysUntil, 12);
  return new Intl.DateTimeFormat(locale, { weekday: "long" }).format(when);
}

export const birthdaysService = {
  /** Friends' birthdays today and in the next `days - 1` days, soonest first. */
  async list(days = 7): Promise<FriendBirthday[]> {
    const { data } = await api.get<{ data: { date: string; days: number; results: FriendBirthday[] } }>("/me/birthdays/", {
      params: { date: localDate(), days },
    });
    return Array.isArray(data.data?.results) ? data.data.results : [];
  },
};
