import { type Page, expect, test } from "@playwright/test";

import { API, apiAs, befriend, expectNoUuid, pageAs, sharedAccounts, unique } from "./helpers";

// Events (roadmap 1.13, 1.14): create, invite, RSVP, capacity full, cancel.
// Arabic (RTL) is the default locale; the last test runs the list in English.

const eventId = (page: Page) => /\/events\/([0-9a-f-]{36})$/.exec(new URL(page.url()).pathname)?.[1] ?? "";

test("create an invite-only event, invite friends, fill it, then cancel it", async ({ browser }) => {
  const { a, b, c } = await sharedAccounts();
  await befriend(a, b);
  await befriend(a, c);
  const title = `أمسية قراءة ${unique()}`;

  // The host creates the event from the form (defaults: tomorrow at 19:00).
  const host = await pageAs(browser, a);
  await host.goto("/events");
  await expect(host.locator("html")).toHaveAttribute("dir", "rtl");
  await host.getByRole("link", { name: "إنشاء فعالية" }).click();
  await expect(host).toHaveURL(/\/events\/new$/);
  await host.getByLabel("اسم الفعالية").fill(title);
  await expect(host.locator("#event-start-date")).toHaveAttribute("dir", "ltr");
  await host.locator("#event-location").fill("مكتبة القاهرة");
  await host.getByRole("radio", { name: /المدعوون فقط/ }).check();
  await host.locator("#event-capacity").fill("1");
  await host.getByRole("button", { name: "إنشاء الفعالية" }).click();
  await expect(host).toHaveURL(/\/events\/[0-9a-f-]{36}$/);
  const id = eventId(host);
  await expect(host.getByRole("heading", { name: title })).toBeVisible();
  await expect(host.getByText("بقي مكان واحد")).toBeVisible();
  await expectNoUuid(host);

  // Nobody else can see it until invited (a hidden event is a 404).
  const guest = await apiAs(b);
  expect((await guest.get(`${API}/events/${id}/`)).status()).toBe(404);

  // Invite both friends.
  await host.getByRole("button", { name: "دعوة الأصدقاء" }).click();
  const dialog = host.getByRole("dialog", { name: "دعوة الأصدقاء" });
  await dialog.getByRole("button", { name: b.name }).click();
  await dialog.getByRole("button", { name: c.name }).click();
  await dialog.getByRole("button", { name: "دعوة صديقين" }).click();
  await expect(host.getByText("أُرسلت دعوتان")).toBeVisible();
  await dialog.getByRole("button", { name: "إغلاق" }).click();

  // The invite reaches b's notifications with a deep link to the event.
  await expect
    .poll(
      async () => {
        const rows = (await (await guest.get(`${API}/notifications/`)).json()).data as { kind: string; url: string }[];
        return rows.find((r) => r.kind === "gathering.invite" && r.url === `/events/${id}`) ? "found" : "";
      },
      { timeout: 30_000 },
    )
    .toBe("found");

  // b takes the only seat.
  const first = await pageAs(browser, b);
  await first.goto(`/events/${id}`);
  await expect(first.getByText("أنت مدعو إلى هذه الفعالية.")).toBeVisible();
  const rsvp = first.getByRole("group", { name: "ردك" });
  await rsvp.getByRole("button", { name: "سأحضر" }).click();
  await expect(rsvp.getByRole("button", { name: "سأحضر" })).toHaveAttribute("aria-pressed", "true");
  await expect(first.getByText("سيحضر شخص واحد")).toBeVisible();
  await expect(first.getByText("لا أماكن متبقية")).toBeVisible();
  await expectNoUuid(first);

  // c finds it full: the button says so, and the API answers 409 event_full.
  const second = await pageAs(browser, c);
  await second.goto(`/events/${id}`);
  await expect(second.getByRole("group", { name: "ردك" }).getByRole("button", { name: "اكتمل العدد" })).toBeDisabled();
  const late = await apiAs(c);
  const full = await late.post(`${API}/events/${id}/rsvp/`, { data: { status: "going" } });
  expect(full.status()).toBe(409);
  expect((await full.json()).error.code).toBe("event_full");

  // The host sees b among the people going, then cancels.
  await host.reload();
  await expect(host.getByRole("tabpanel").getByText(b.name)).toBeVisible();
  host.once("dialog", (d) => d.accept());
  await host.getByRole("button", { name: "خيارات أخرى" }).click();
  await host.getByRole("menuitem", { name: "إلغاء الفعالية" }).click();
  await expect(host.getByText("أُلغيت", { exact: true })).toBeVisible();

  // b now sees a cancelled event with no RSVP control.
  await first.reload();
  await expect(first.getByText("أُلغيت", { exact: true })).toBeVisible();
  await expect(first.getByRole("group", { name: "ردك" })).toHaveCount(0);
  const again = await guest.post(`${API}/events/${id}/rsvp/`, { data: { status: "going" } });
  expect((await again.json()).error.code).toBe("event_cancelled");

  await guest.dispose();
  await late.dispose();
});

test("the events list in English, with a hosted event under Hosting", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const api = await apiAs(a);
  const title = `Board games ${unique()}`;
  const starts = new Date(Date.now() + 3 * 24 * 3600 * 1000).toISOString();
  const created = await api.post(`${API}/events/`, {
    data: { title, starts_at: starts, location: "Cafe", timezone: "Africa/Cairo" },
  });
  expect(created.status(), await created.text()).toBe(201);

  const page = await pageAs(browser, a);
  await page.addInitScript(() => localStorage.setItem("tara.locale", "en"));
  await page.goto("/events");
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  const tabs = page.getByRole("tablist", { name: "Events" });
  for (const name of ["Upcoming", "Hosting", "Going", "Invited", "Past"]) {
    await expect(tabs.getByRole("tab", { name })).toBeVisible();
  }
  await tabs.getByRole("tab", { name: "Hosting" }).click();
  await expect(page).toHaveURL(/tab=hosting/);
  const card = page.locator("article").filter({ hasText: title });
  await expect(card).toBeVisible();
  await expect(card.getByText("You're hosting")).toBeVisible();
  await card.getByRole("link").click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByRole("group", { name: "Your answer" })).toHaveCount(0); // the host does not RSVP
  await expectNoUuid(page);
  await api.dispose();
});
