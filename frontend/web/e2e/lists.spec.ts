import { expect, test } from "@playwright/test";

import { API, apiAs, dmWith, pageAs, sharedAccounts, unique } from "./helpers";

test("Seen survives a reload, and the inbox follows the latest message", async ({ browser }) => {
  const { a, b, c } = await sharedAccounts();
  const tag = unique();
  const alice = await apiAs(a);
  const bob = await apiAs(b);
  const withBob = await dmWith(alice, b.id);
  const withCarol = await dmWith(alice, c.id);

  const sent = await alice.post(`${API}/conversations/${withBob}/messages/`, { data: { body: `seen ${tag}` } });
  const messageId = (await sent.json()).data.id;
  await alice.post(`${API}/conversations/${withCarol}/messages/`, { data: { body: `later ${tag}` } });
  await bob.post(`${API}/conversations/${withBob}/read/`, { data: { up_to_message_id: messageId } });

  const page = await pageAs(browser, a);
  await page.goto(`/messages/${withBob}`);
  await expect(page.getByText("تمت القراءة")).toBeVisible();
  await page.reload();
  await expect(page.getByText("تمت القراءة")).toBeVisible();

  const rows = page.locator("ul li button");
  await expect(rows.first()).toContainText(c.name);
  await alice.post(`${API}/conversations/${withBob}/messages/`, { data: { body: `bump ${tag}` } });
  await page.reload();
  await expect(rows.first()).toContainText(b.name);
});

test("comments page with a load-more button", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const tag = unique();
  const api = await apiAs(a);
  const created = await api.post(`${API}/posts/`, { data: { body: `paged ${tag}`, audience: "public" } });
  const postId = (await created.json()).data.id;
  for (let i = 0; i < 23; i++) {
    await api.post(`${API}/posts/${postId}/comments/`, { data: { body: `comment-${i}-${tag}` } });
  }

  const page = await pageAs(browser, a);
  await page.goto(`/posts/${postId}`);
  await expect(page.getByText(`comment-0-${tag}`)).toBeVisible();
  await expect(page.getByText(`comment-22-${tag}`)).toHaveCount(0);
  await page.getByRole("button", { name: "عرض مزيد من التعليقات" }).click();
  await expect(page.getByText(`comment-22-${tag}`)).toBeVisible();
  await expect(page.getByRole("button", { name: "عرض مزيد من التعليقات" })).toHaveCount(0);
});

test("quiet hours save only as a whole window", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.goto("/settings");
  const patches: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "PATCH" && r.url().includes("/notifications/preferences/")) {
      patches.push(r.postData() ?? "");
    }
  });
  const from = page.getByRole("textbox", { name: "من", exact: true });
  const to = page.getByRole("textbox", { name: "إلى", exact: true });
  await expect(from).toBeVisible();
  const off = page.getByRole("button", { name: "إيقاف" });
  if (await off.isVisible()) {
    await off.click();
    await expect(off).toHaveCount(0);
  }
  patches.length = 0;
  await from.fill("22:00");
  await page.waitForTimeout(300);
  expect(patches).toEqual([]);

  const saved = page.waitForResponse((r) => r.url().includes("/notifications/preferences/") && r.request().method() === "PATCH");
  await to.fill("07:00");
  expect((await saved).status()).toBe(200);
  await page.reload();
  await expect(from).toHaveValue("22:00");
  await expect(to).toHaveValue("07:00");
  await page.getByRole("button", { name: "إيقاف" }).click();
  await page.waitForResponse((r) => r.url().includes("/notifications/preferences/") && r.request().method() === "PATCH");
});
