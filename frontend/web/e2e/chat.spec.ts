import { expect, type Page, test, type WebSocketRoute } from "@playwright/test";

import { API, apiAs, dmWith, expectNoUuid, pageAs, sharedAccounts, unique } from "./helpers";

const composerOf = (page: Page) => page.getByRole("textbox", { name: "اكتب رسالة…" });
const bubbles = (page: Page) => page.getByTestId("message-scroller").locator("p[dir=auto]");
const headerName = (page: Page) => page.getByTestId("conversation-title");

async function send(page: Page, text: string) {
  await composerOf(page).fill(text);
  await page.getByRole("button", { name: "إرسال" }).click();
}

test("two users chat live, in order, with read receipts", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const tag = unique();

  const alice = await pageAs(browser, a);
  await alice.goto(`/u/id/${b.id}`);
  await alice.getByRole("button", { name: "مراسلة" }).click();
  await expect(alice).toHaveURL(/\/messages\/[\w-]+$/);
  await expect(headerName(alice)).toHaveText(b.name);

  const bob = await pageAs(browser, b);
  await bob.goto(new URL(alice.url()).pathname);
  await expect(headerName(bob)).toHaveText(a.name);
  await bob.waitForTimeout(800); // Let the socket connect.

  await send(alice, `first ${tag}`);
  await expect(bubbles(bob).last()).toHaveText(`first ${tag}`);
  await expect(alice.locator('[data-testid="message-status"][data-status="read"]').last()).toBeVisible();

  await send(bob, `second ${tag}`);
  await expect(bubbles(alice).last()).toHaveText(`second ${tag}`);
  await send(alice, `third ${tag}`);
  await expect(bubbles(bob).last()).toHaveText(`third ${tag}`);

  // The API pages newest first; the screen must still read top to bottom.
  await alice.reload();
  await expect(bubbles(alice).last()).toHaveText(`third ${tag}`);
  const texts = await bubbles(alice).allTextContents();
  expect(texts.filter((t) => t.endsWith(tag)).slice(-3)).toEqual([
    `first ${tag}`,
    `second ${tag}`,
    `third ${tag}`,
  ]);
  await expectNoUuid(alice);
});

test("scrolling up loads older pages in place, and new messages raise the pill", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const tag = unique();
  const api = await apiAs(a);
  const conversation = await dmWith(api, b.id);
  for (let i = 0; i < 45; i++) {
    await api.post(`${API}/conversations/${conversation}/messages/`, { data: { body: `old ${tag} ${i}` } });
  }

  const reader = await pageAs(browser, b);
  await reader.goto(`/messages/${conversation}`);
  await expect(bubbles(reader).last()).toHaveText(`old ${tag} 44`);
  const scroller = reader.getByTestId("message-scroller");

  // Opens at the true newest message.
  const distance = () => scroller.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight);
  await expect.poll(distance).toBeLessThan(5);
  await reader.waitForTimeout(800); // Let the socket connect.

  // Scroll up: an older page arrives and the message on screen doesn't jump.
  const count = await bubbles(reader).count();
  const anchor = bubbles(reader).first();
  const anchorText = (await anchor.textContent())!;
  await scroller.evaluate((el) => (el.scrollTop = 0));
  await expect.poll(() => bubbles(reader).count()).toBeGreaterThan(count);
  await expect(bubbles(reader).filter({ hasText: new RegExp(`^${anchorText}$`) })).toBeInViewport();

  // Page all the way to the start.
  const oldest = bubbles(reader).filter({ hasText: new RegExp(`^old ${tag} 0$`) });
  await expect
    .poll(async () => {
      await scroller.evaluate((el) => (el.scrollTop = 0));
      return oldest.count();
    })
    .toBe(1);

  // More than one page is loaded now, and the reader is far from the bottom.
  expect(await bubbles(reader).count()).toBeGreaterThan(20);
  await api.post(`${API}/conversations/${conversation}/messages/`, { data: { body: `new ${tag}` } });
  const pill = reader.getByRole("button", { name: "رسائل جديدة" });
  await expect(pill).toBeVisible();
  await expect(bubbles(reader).filter({ hasText: `new ${tag}` })).toHaveCount(1);
  await expect(oldest).toHaveCount(1); // History stayed: the list was merged, not replaced.

  // The pill is centred, in RTL too.
  const box = (await pill.boundingBox())!;
  const pane = (await scroller.boundingBox())!;
  expect(Math.abs(box.x + box.width / 2 - (pane.x + pane.width / 2))).toBeLessThan(3);

  await pill.click();
  await expect(pill).toHaveCount(0);
  await expect(bubbles(reader).last()).toHaveText(`new ${tag}`);
  await expect.poll(distance).toBeLessThan(5);
  await api.dispose();
});

test("a failed send shows an error and keeps the text", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const api = await apiAs(a);
  const conversation = await dmWith(api, b.id);
  await api.dispose();

  const page = await pageAs(browser, a);
  await page.goto(`/messages/${conversation}`);
  await expect(composerOf(page)).toBeVisible();
  await page.route("**/messages/", (route) =>
    route.request().method() === "POST" ? route.abort() : route.continue(),
  );
  await send(page, "will not arrive");
  await expect(page.getByRole("status").filter({ hasText: "لم تُرسل رسالتك" })).toBeVisible();
  await expect(composerOf(page)).toHaveValue("will not arrive");
});

test("a dropped socket reconnects, re-subscribes and catches up", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const tag = unique();
  const api = await apiAs(a);
  const conversation = await dmWith(api, b.id);

  const page = await pageAs(browser, b);
  const sockets: WebSocketRoute[] = [];
  const sent: string[] = [];
  await page.routeWebSocket(/\/ws\/v1\//, (ws) => {
    const server = ws.connectToServer();
    sockets.push(ws);
    ws.onMessage((message) => {
      sent.push(String(message));
      server.send(message);
    });
  });
  await page.goto(`/messages/${conversation}`);
  await expect(composerOf(page)).toBeVisible();
  await expect.poll(() => sent.filter((f) => f.includes(conversation)).length).toBeGreaterThan(0);
  sent.length = 0;

  await sockets[0].close();
  await api.post(`${API}/conversations/${conversation}/messages/`, { data: { body: `missed ${tag}` } });

  await expect(bubbles(page).last()).toHaveText(`missed ${tag}`, { timeout: 30_000 });
  expect(sockets.length).toBeGreaterThan(1);
  expect(sent.some((f) => f.includes('"subscribe"') && f.includes(conversation))).toBe(true);
  await api.dispose();
});
