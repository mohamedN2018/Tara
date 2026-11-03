import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import { API, apiAs, expectNoUuid, pageAs, sharedAccounts, unique } from "./helpers";

test("create a post from the composer", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.goto("/home");

  const text = `منشور تجريبي ${unique()}`;
  await page.getByRole("button", { name: "بماذا تفكر؟" }).click();
  await page.getByRole("textbox", { name: "بماذا تفكر؟" }).fill(text);
  await page.getByRole("button", { name: "نشر", exact: true }).click();

  const post = page.locator("article").filter({ hasText: text });
  await expect(post).toBeVisible();
  await expect(post.getByRole("link", { name: a.name }).first()).toBeVisible();
  await expect(post.locator("p[dir=auto]")).toBeVisible();
  await expectNoUuid(page);
});

test("editing a long post from the feed keeps every character", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const marker = unique();
  // Past the feed's 280-character excerpt, with the marker beyond the cut.
  const body = `${"نص طويل جدا ".repeat(40)}END-${marker}`;
  expect(body.length).toBeGreaterThan(280);

  const api = await apiAs(a);
  const created = await api.post(`${API}/posts/`, { data: { body, audience: "public", type: "text" } });
  expect(created.ok()).toBe(true);

  const page = await pageAs(browser, a);
  const post = page.locator("article").filter({ hasText: `END-${marker}` });
  // Fan-out to the feed is asynchronous.
  await expect
    .poll(async () => {
      await page.goto("/home");
      await page.locator("article").first().waitFor();
      return post.count();
    })
    .toBe(1);

  await post.getByRole("button", { name: "المزيد" }).click();
  await post.getByRole("button", { name: "تعديل" }).click();
  // While editing, the text lives in the textarea: `post` no longer matches.
  const editor = page.getByRole("textbox", { name: "تعديل نص المنشور" });
  await expect(editor).toHaveValue(body);

  await editor.fill(`${body} EDITED`);
  await page.locator("article").filter({ has: editor }).getByRole("button", { name: "حفظ", exact: true }).last().click();
  await expect(post).toContainText(`END-${marker} EDITED`);

  await page.reload();
  await expect(page.locator("article").filter({ hasText: `END-${marker} EDITED` })).toBeVisible();
  await api.dispose();
});

test("a feed that can't be hydrated shows snapshots and refuses to edit them", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.route("**/posts/batch/", (route) => route.fulfill({ status: 503, body: "down" }));
  await page.goto("/home");
  const post = page.locator("article").first();
  await expect(post).toBeVisible();
  await post.getByRole("button", { name: "المزيد" }).click();
  await expect(post.getByRole("button", { name: "تعديل" })).toHaveCount(0);
  await expect(post.getByRole("button", { name: "حذف" })).toBeVisible();
});

test("a post deleted since it reached the feed is dropped", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.route("**/posts/batch/", (route) => route.fulfill({ json: { data: [] } }));
  await page.goto("/home");
  await expect(page.getByText("لا توجد منشورات بعد")).toBeVisible();
});

test("my reaction and saved state come back after a reload", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const marker = unique();
  const api = await apiAs(a);
  const { data: post } = await (
    await api.post(`${API}/posts/`, { data: { body: `state ${marker}`, audience: "public", type: "text" } })
  ).json();
  await api.dispose();

  const reader = await apiAs(b);
  await reader.post(`${API}/posts/${post.id}/reactions/`, { data: { type: "love" } });
  await reader.post(`${API}/posts/${post.id}/save/`);
  await reader.dispose();

  const page = await pageAs(browser, b);
  await page.goto(`/posts/${post.id}`);
  const card = page.locator("article");
  await expect(card.getByRole("button", { name: "أحببته" })).toHaveAttribute("aria-pressed", "true");
  await expect(card.getByRole("button", { name: "حفظ" })).toHaveAttribute("aria-pressed", "true");
});

test("a failed action shows a toast, not a browser alert", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const marker = unique();
  const api = await apiAs(a);
  const { data: post } = await (
    await api.post(`${API}/posts/`, { data: { body: `doomed ${marker}`, audience: "public", type: "text" } })
  ).json();
  await api.dispose();

  const page = await pageAs(browser, a);
  let dialogs = 0;
  page.on("dialog", (dialog) => {
    dialogs += 1;
    void dialog.dismiss();
  });
  await page.goto(`/posts/${post.id}`);
  await page.route(`**/posts/${post.id}/`, (route) =>
    route.request().method() === "DELETE"
      ? route.fulfill({ status: 403, json: { error: { code: "permission_denied", message: "raw english" } } })
      : route.continue(),
  );
  const card = page.locator("article");
  await card.getByRole("button", { name: "المزيد" }).click();
  await card.getByRole("button", { name: "حذف" }).click();
  await expect(page.getByRole("status").filter({ hasText: "غير مسموح لك بهذا الإجراء" })).toBeVisible();
  expect(dialogs).toBe(0);
});

test("a comment link opens the reply's thread, scrolls to it and highlights it", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const marker = unique();
  const api = await apiAs(a);
  const { data: post } = await (
    await api.post(`${API}/posts/`, { data: { body: `deep link ${marker}`, audience: "public", type: "text" } })
  ).json();
  const comment = async (path: string, body: string) =>
    (await (await api.post(`${API}${path}`, { data: { body } })).json()).data as { id: string };
  // Past the first page of roots (20), so the root itself has to be paged in.
  const roots: { id: string }[] = [];
  for (let i = 0; i < 22; i++) roots.push(await comment(`/posts/${post.id}/comments/`, `root ${i} ${marker}`));
  const root = roots[21];
  await comment(`/comments/${root.id}/replies/`, `first reply ${marker}`);
  const reply = await comment(`/comments/${root.id}/replies/`, `target reply ${marker}`);
  await api.dispose();

  const page = await pageAs(browser, b);
  await page.emulateMedia({ reducedMotion: "reduce" });
  // No thread hint (a push link): the page has to search the threads.
  await page.goto(`/posts/${post.id}?comment=${reply.id}`);
  const target = page.locator(`[data-comment-id="${reply.id}"]`);
  await expect(target).toContainText(`target reply ${marker}`);
  await expect(target).toHaveAttribute("data-highlighted", "true");
  await expect(target).toBeInViewport();
  await expect(target).toBeFocused();
  // The highlight is brief.
  await expect(target).not.toHaveAttribute("data-highlighted", "true", { timeout: 5_000 });

  // With the hint an in-app notification adds, and for a root.
  await page.goto(`/posts/${post.id}?comment=${reply.id}&thread=${root.id}`);
  await expect(page.locator(`[data-comment-id="${reply.id}"]`)).toHaveAttribute("data-highlighted", "true");
  await page.goto(`/posts/${post.id}?comment=${roots[20].id}`);
  await expect(page.locator(`[data-comment-id="${roots[20].id}"]`)).toBeInViewport();
  await expectNoUuid(page);
});

test("an iPhone photo uploads as HEIC and shows a placeholder in the composer", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const page = await pageAs(browser, a);
  await page.goto("/home");
  const signed: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/media/uploads/sign/")) signed.push(String(req.postDataJSON()?.mime));
  });

  await page.getByRole("button", { name: "بماذا تفكر؟" }).click();
  // An empty type, as Chrome on Windows reports for .heic: the app names it.
  await page.getByLabel("إضافة صور").last().setInputFiles({
    name: "IMG_0001.HEIC",
    mimeType: "",
    buffer: readFileSync(fileURLToPath(new URL("./fixtures/photo.heic", import.meta.url))),
  });
  await expect(page.getByTestId("heic-placeholder")).toBeVisible();
  expect(signed).toEqual(["image/heic"]);

  const text = `heic ${unique()}`;
  await page.getByRole("textbox", { name: "بماذا تفكر؟" }).fill(text);
  const created = page.waitForResponse((r) => r.url().endsWith("/posts/") && r.request().method() === "POST");
  await page.getByRole("button", { name: "نشر", exact: true }).click();
  const { data: post } = await (await created).json();

  // The server stores a JPEG copy, which any browser can draw once processed.
  const photo = page.getByTestId("media-grid").locator("img");
  await expect
    .poll(
      async () => {
        await page.goto(`/posts/${post.id}`);
        // The URL resolves after the first render; give the tile a moment to appear.
        if (!(await photo.first().waitFor({ timeout: 5_000 }).then(() => true, () => false))) return 0;
        return photo.evaluate((img: HTMLImageElement) => img.decode().then(() => img.naturalWidth, () => 0));
      },
      { timeout: 45_000 },
    )
    .toBeGreaterThan(0);
});
