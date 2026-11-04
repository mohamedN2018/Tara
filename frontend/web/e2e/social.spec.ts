import { expect, test } from "@playwright/test";

import { API, apiAs, befriend, expectNoUuid, pageAs, sharedAccounts, unfriend, unique } from "./helpers";

test("field privacy from the edit modal hides a field from others", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const tag = unique();
  const api = await apiAs(a);
  await api.patch(`${API}/profile/me/`, { data: { bio: `bio ${tag}` } });

  const owner = await pageAs(browser, a);
  await owner.goto(`/u/id/${a.id}`);
  await owner.getByRole("button", { name: /تعديل الملف/ }).first().click();
  const section = owner.getByTestId("field-privacy");
  await section.locator("label", { hasText: "النبذة" }).locator("select").selectOption("private");
  await owner.getByRole("button", { name: /^حفظ/ }).last().click();
  await expect(section).toHaveCount(0);

  const other = await pageAs(browser, b);
  await other.goto(`/u/id/${a.id}`);
  await expect(other.getByText(new RegExp(a.name)).first()).toBeVisible();
  await expect(other.getByText(`bio ${tag}`)).toHaveCount(0);

  await owner.reload();
  await expect(owner.getByText(`bio ${tag}`).first()).toBeVisible(); // Still shown to the owner.
  await api.put(`${API}/profile/me/privacy/`, { data: { items: [{ field_key: "bio", visibility: "public" }] } });
  await other.reload();
  await expect(other.getByText(`bio ${tag}`).first()).toBeVisible();
});

test("#hashtags link to their posts and @mentions autocomplete and notify", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const tag = `تاج${unique()}`;

  const page = await pageAs(browser, a);
  await page.goto("/home");
  await page.getByRole("button", { name: "بماذا تفكر" }).first().click().catch(() => {});
  const composer = page.getByRole("textbox", { name: /بماذا تفكر/ });
  await composer.pressSequentially(`مرحبا #${tag} @${b.handle.slice(0, 6)}`);
  const option = page.getByTestId("mention-list").getByRole("option").first();
  await expect(option).toContainText(b.handle);
  await composer.press("Enter");
  await expect(composer).toHaveValue(`مرحبا #${tag} @${b.handle} `);
  await page.getByRole("button", { name: "نشر", exact: true }).click();

  const post = page.locator("article", { hasText: tag }).first();
  await expect(post).toBeVisible();
  await post.getByRole("link", { name: `@${b.handle}` }).isVisible();
  await post.getByRole("link", { name: `#${tag}` }).click();
  await expect(page).toHaveURL(/\/search\?q=/);
  await expect(page.locator("article", { hasText: tag })).toHaveCount(1);

  const bobApi = await apiAs(b);
  await expect
    .poll(async () => {
      const list = await (await bobApi.get(`${API}/notifications/`)).json();
      return list.data.some((n: { kind: string; actor_id: string }) => n.kind === "mention" && n.actor_id === a.id);
    }, { timeout: 20_000 })
    .toBe(true);
  const bob = await pageAs(browser, b);
  await bob.goto("/notifications");
  await expect(bob.getByText(`أشار إليك ${a.name}`).first()).toBeVisible();
  await expectNoUuid(bob);
});

test("sharing creates a card, and a friends-only original stays hidden from others", async ({ browser }) => {
  const { a, b, c } = await sharedAccounts();
  const tag = unique();
  const alice = await apiAs(a);
  const friendsOnly = await alice.post(`${API}/posts/`, { data: { body: `secret ${tag}`, audience: "friends" } });
  const originalId = (await friendsOnly.json()).data.id;
  const publicPost = await alice.post(`${API}/posts/`, { data: { body: `open ${tag}`, audience: "public" } });
  const publicId = (await publicPost.json()).data.id;

  // Bob shares the public post through the UI.
  const bob = await pageAs(browser, b);
  await bob.goto(`/posts/${publicId}`);
  await bob.getByRole("button", { name: "مشاركة", exact: true }).click();
  await bob.getByTestId("share-box").getByRole("textbox").fill(`bob says ${tag}`);
  await bob.getByRole("button", { name: "مشاركة الآن" }).click();
  await expect(bob.getByText("تمت المشاركة على صفحتك.")).toBeVisible();

  // Carol is Bob's friend but not Alice's: she may read Bob's words, not Alice's.
  await befriend(a, b);
  await befriend(b, c);
  await unfriend(a, c);

  const bobApi = await apiAs(b);
  const blocked = await bobApi.post(`${API}/posts/${originalId}/share/`, { data: { audience: "public" } });
  expect(blocked.status()).toBe(400);
  const shared = await bobApi.post(`${API}/posts/${originalId}/share/`, { data: { audience: "friends", body: `wrap ${tag}` } });
  expect(shared.status()).toBe(201);
  const shareId = (await shared.json()).data.id;

  const bobPage = await pageAs(browser, b);
  await bobPage.goto(`/posts/${shareId}`);
  await expect(bobPage.getByTestId("shared-post")).toContainText(`secret ${tag}`);

  const carol = await pageAs(browser, c);
  await carol.goto(`/posts/${shareId}`);
  await expect(carol.getByText(`wrap ${tag}`)).toBeVisible();
  await expect(carol.getByTestId("shared-post")).toContainText("هذا المنشور غير متاح.");
  await expect(carol.getByText(`secret ${tag}`)).toHaveCount(0);
});

test("a poll is created, voted on once, and shows results", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const tag = unique();
  const page = await pageAs(browser, a);
  await page.goto("/home");
  await page.getByRole("button", { name: "بماذا تفكر" }).first().click().catch(() => {});
  await page.getByRole("button", { name: "استطلاع" }).click();
  await page.getByRole("textbox", { name: "اطرح سؤالًا…" }).fill(`سؤال ${tag}؟`);
  await page.getByRole("textbox", { name: "الخيار 1" }).fill("شاي");
  await page.getByRole("textbox", { name: "الخيار 2" }).fill("قهوة");
  await page.getByRole("button", { name: "نشر", exact: true }).click();
  const post = page.locator("article", { hasText: tag }).first();
  await expect(post.getByTestId("poll")).toBeVisible();

  const postId = await post.getByRole("link", { name: /الآن|ثانية|دقيقة|now/ }).first().getAttribute("href");
  const voter = await pageAs(browser, b);
  await voter.goto(postId as string);
  await voter.getByRole("button", { name: "قهوة" }).click();
  await expect(voter.getByTestId("poll")).toContainText("100%");
  await expect(voter.getByTestId("poll")).toContainText("صوت واحد");
  await voter.reload();
  await expect(voter.getByTestId("poll")).toContainText("100%");
  await expect(voter.getByRole("button", { name: "قهوة" })).toHaveCount(0);
});

test("pages can be created, found, edited, and their team managed", async ({ browser }) => {
  const { a, b } = await sharedAccounts();
  const tag = unique();
  const page = await pageAs(browser, a);
  await page.goto("/pages");
  await page.getByRole("button", { name: "إنشاء صفحة" }).click();
  await page.getByLabel("اسم الصفحة").fill(`مقهى ${tag}`);
  await page.getByLabel("المعرّف").fill(`cafe_${tag}`);
  await page.getByLabel("الفئة").fill("مطاعم");
  await page.getByRole("dialog").getByRole("button", { name: "إنشاء صفحة" }).click();
  await expect(page).toHaveURL(new RegExp(`/pages/cafe_${tag}$`));
  await expect(page.getByTestId("page-name")).toHaveText(`مقهى ${tag}`);

  // The team is its own tab of the page (T3), shown to the page's team only.
  await page.getByTestId("page-tab-team").click();
  await page.getByRole("textbox", { name: "@المعرّف" }).fill(b.handle);
  await page.getByRole("button", { name: "إضافة", exact: true }).click();
  await expect(page.getByTestId("page-members")).toContainText(b.name);
  await page
    .getByTestId("page-members")
    .locator("li", { hasText: b.name })
    .locator("select")
    .selectOption("analyst");

  const other = await pageAs(browser, b);
  await other.goto("/pages?tab=manage");
  await expect(other.getByRole("main").getByText(`مقهى ${tag}`)).toBeVisible();
  await other.getByRole("main").getByText(`مقهى ${tag}`).click();
  await other.getByTestId("page-tab-team").click();
  await expect(other.getByTestId("page-members")).toContainText("محلل");
  await expect(other.getByRole("textbox", { name: "@المعرّف" })).toHaveCount(0);

  await page.getByTestId("page-edit").click();
  await page.getByRole("textbox", { name: "نبذة" }).fill(`عن المقهى ${tag}`);
  await page.getByTestId("page-edit-save").click();
  await page.getByTestId("page-tab-about").click();
  await expect(page.getByText(`عن المقهى ${tag}`)).toBeVisible();
  await expectNoUuid(page);
});

test("a link preview comes from the server, and an internal URL gets none", async () => {
  const { a } = await sharedAccounts();
  const tag = unique();
  const api = await apiAs(a);

  // The client's preview field is ignored, and internal addresses are refused.
  const internal = await api.post(`${API}/posts/`, {
    data: {
      body: `internal ${tag} http://169.254.169.254/latest/meta-data/ http://minio:9000/`,
      link_preview: { url: "http://evil", title: "forged" },
    },
  });
  const id = (await internal.json()).data.id;
  await new Promise((r) => setTimeout(r, 4000));
  const post = (await (await api.get(`${API}/posts/${id}/`)).json()).data;
  expect(post.link_preview).toBeNull();
});

// Needs outbound internet from the post-consumer container.
test("a post with a link gets a server-built preview card", async ({ browser }) => {
  const { a } = await sharedAccounts();
  const tag = unique();
  const page = await pageAs(browser, a);
  await page.goto("/home");
  await page.getByRole("button", { name: "بماذا تفكر" }).first().click().catch(() => {});
  await page.getByRole("textbox", { name: /بماذا تفكر/ }).fill(`link ${tag} https://example.com/`);
  await page.getByRole("button", { name: "نشر", exact: true }).click();
  const post = page.locator("article", { hasText: tag }).first();
  await expect(post.getByTestId("link-preview")).toContainText("Example Domain", { timeout: 15_000 });
  await expect(post.getByTestId("link-preview")).toHaveAttribute("rel", /noopener/);
});
