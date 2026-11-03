import { type Page, expect, test } from "@playwright/test";

import { API, apiAs, expectNoUuid, pageAs, sharedAccounts, unique } from "./helpers";

// Groups (roadmap 1.11, 1.12): create a private group with membership approval,
// a second account asks to join and the owner approves, the member posts, a
// moderator removes the post, and the owner bans the member.
// Arabic (RTL) is the default locale.

test.describe.configure({ mode: "serial" });

const acceptDialogs = (page: Page) => page.on("dialog", (d) => d.accept());

test("create a private group, approve a member, post, moderate and ban", async ({ browser }) => {
  const { a, b, c } = await sharedAccounts();
  const tag = unique();
  const handle = `e2e_club_${tag}`;
  const name = `نادي القراءة ${tag}`;
  const body = `أول منشور في النادي ${tag}`;

  // 1. The owner creates a private group that approves new members.
  const owner = await pageAs(browser, a);
  acceptDialogs(owner);
  await owner.goto("/groups");
  await expect(owner.locator("html")).toHaveAttribute("dir", "rtl");
  await owner.getByRole("link", { name: "إنشاء مجموعة جديدة" }).click();
  await expect(owner).toHaveURL(/\/groups\/new$/);
  await owner.getByLabel("اسم المجموعة").fill(name);
  await owner.getByLabel("عنوان المجموعة").fill(handle);
  await expect(owner.getByText("هذا العنوان متاح.")).toBeVisible();
  await owner.getByRole("radio", { name: /مجموعة خاصة/ }).check();
  await owner.getByRole("checkbox", { name: /الموافقة على الأعضاء الجدد/ }).check();
  await owner.getByRole("button", { name: "إنشاء المجموعة" }).click();
  await expect(owner).toHaveURL(new RegExp(`/groups/${handle}$`));
  await expect(owner.getByRole("heading", { name })).toBeVisible();
  await expect(owner.getByTestId("group-privacy").first()).toHaveText(/مجموعة خاصة/);
  await expect(owner.getByTestId("group-member-count")).toHaveText("عضو واحد");
  await expectNoUuid(owner);

  // 2. A stranger sees the header but not the content, and asks to join.
  const memberApi = await apiAs(b);
  const seen = (await (await memberApi.get(`${API}/groups/${handle}/`)).json()).data;
  expect(seen.content_visible).toBe(false);
  expect((await memberApi.get(`${API}/posts/groups/${seen.id}/`)).status()).toBe(404);
  const member = await pageAs(browser, b);
  await member.goto(`/groups/${handle}`);
  await expect(member.getByText("هذه المجموعة خاصة")).toBeVisible();
  await member.getByRole("button", { name: "اطلب الانضمام" }).click();
  await expect(member.getByTestId("group-join").getByRole("button", { name: /تم إرسال الطلب/ })).toBeVisible();

  // 3. The owner approves the request from the dashboard.
  await owner.goto(`/groups/${handle}/manage`);
  await expect(owner.getByRole("heading", { name: "طلبات الانضمام" })).toBeVisible();
  await owner.getByRole("button", { name: `الموافقة على ${b.name}` }).click();
  await expect(owner.getByText(`أصبح ${b.name} عضوًا.`)).toBeVisible();

  // 4. The member posts in the group.
  await member.reload();
  await expect(member.getByTestId("group-join").getByRole("button", { name: /عضو/ })).toBeVisible();
  await member.getByRole("button", { name: "اكتب شيئًا للمجموعة…" }).click();
  await member.getByPlaceholder("اكتب شيئًا للمجموعة…").fill(body);
  await member.getByRole("button", { name: "نشر", exact: true }).click();
  const post = member.getByTestId("group-post").filter({ hasText: body });
  await expect(post).toBeVisible();
  await expectNoUuid(member);

  // 5. A third account joins and is made a moderator; it removes the post.
  const ownerApi = await apiAs(a);
  const modApi = await apiAs(c);
  expect((await modApi.post(`${API}/groups/${handle}/join/`)).status()).toBe(201);
  expect((await ownerApi.post(`${API}/groups/${handle}/requests/${c.id}/approve/`)).ok()).toBe(true);
  expect((await ownerApi.patch(`${API}/groups/${handle}/members/${c.id}/`, { data: { role: "moderator" } })).ok()).toBe(true);
  const postId = ((await (await memberApi.get(`${API}/posts/groups/${seen.id}/`)).json()).data as { id: string; body: string }[]).find(
    (p) => p.body === body,
  )?.id;
  expect(postId).toBeTruthy();

  const moderator = await pageAs(browser, c);
  acceptDialogs(moderator);
  await moderator.goto(`/groups/${handle}`);
  const modPost = moderator.getByTestId("group-post").filter({ hasText: body });
  await expect(modPost).toBeVisible();
  await modPost.getByRole("button", { name: "المزيد" }).click();
  await modPost.getByRole("button", { name: "حذف", exact: true }).click();
  await expect(modPost).toHaveCount(0);
  expect((await memberApi.get(`${API}/posts/${postId}/`)).status()).toBe(404);

  // 6. The owner bans the member, who then loses the group (404) and cannot post.
  await owner.goto(`/groups/${handle}/manage?section=members`);
  await owner.getByRole("button", { name: `حظر ${b.name}` }).click();
  await expect(owner.getByText(`حُظر ${b.name}.`)).toBeVisible();
  await owner.goto(`/groups/${handle}/manage?section=banned`);
  await expect(owner.getByRole("button", { name: `إلغاء حظر ${b.name}` })).toBeVisible();
  expect((await memberApi.get(`${API}/groups/${handle}/`)).status()).toBe(404);
  const blocked = await memberApi.post(`${API}/posts/`, { data: { body: "still here?", group_id: seen.id } });
  expect([403, 404]).toContain(blocked.status());
  await member.goto(`/groups/${handle}`);
  await expect(member.getByText("404")).toBeVisible();
});
