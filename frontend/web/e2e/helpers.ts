import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { type APIRequestContext, type Browser, type Page, expect, request } from "@playwright/test";

export const API = process.env.E2E_API ?? "http://127.0.0.1:8080/api/v1";
export const MAILPIT = process.env.E2E_MAILPIT ?? "http://127.0.0.1:8026/api/v1";
export const PASSWORD = "Str0ng-Pass-987!";

const ACCOUNTS_FILE = join(dirname(fileURLToPath(import.meta.url)), ".accounts.json");

export interface Account {
  email: string;
  handle: string;
  name: string;
  id: string;
}

export const unique = () => Math.random().toString(36).slice(2, 8);

/** Poll Mailpit for the newest mail to `email` and return its verification token. */
export async function verificationToken(api: APIRequestContext, email: string): Promise<string> {
  let id: string | undefined;
  await expect
    .poll(
      async () => {
        const res = await api.get(`${MAILPIT}/search`, { params: { query: `to:${email}` } });
        id = (await res.json()).messages?.[0]?.ID;
        return id;
      },
      { timeout: 30_000 },
    )
    .toBeTruthy();
  const message = await (await api.get(`${MAILPIT}/message/${id}`)).json();
  const match = /token=([\w\-.:%]+)/.exec(message.Text as string);
  if (!match) throw new Error(`no token in mail to ${email}`);
  return match[1];
}

async function apiLogin(
  api: APIRequestContext,
  email: string,
): Promise<{ access: string; refresh: string } | null> {
  const res = await api.post(`${API}/auth/login/`, { data: { email, password: PASSWORD } });
  if (res.status() === 401) return null;
  if (!res.ok()) throw new Error(`login failed (${res.status()}): is the stack up?`);
  const { data } = await res.json();
  return { access: data.access_token, refresh: data.refresh_token };
}

async function createAccount(api: APIRequestContext, slot: string): Promise<Account> {
  const tag = unique();
  const handle = `e2e_${slot}_${tag}`;
  const email = `${handle}@example.com`;
  const name = `${slot === "a" ? "ليلى" : "Omar"} ${tag}`;
  const res = await api.post(`${API}/auth/register/`, {
    data: { email, password: PASSWORD, handle, display_name: name, language: "ar" },
  });
  expect(res.status(), await res.text()).toBe(201);
  const token = await verificationToken(api, email);
  expect((await api.post(`${API}/auth/verify-email/`, { data: { token } })).ok()).toBe(true);
  const { data } = await res.json();
  return { email, handle, name, id: data.account_id };
}

/**
 * Two long-lived accounts. Registration is limited to 10 an hour per IP, so
 * they are kept in e2e/.accounts.json between runs and only recreated when gone.
 */
export async function sharedAccounts(): Promise<{ a: Account; b: Account }> {
  const api = await request.newContext();
  try {
    if (existsSync(ACCOUNTS_FILE)) {
      const saved = JSON.parse(readFileSync(ACCOUNTS_FILE, "utf8"));
      if ((await apiLogin(api, saved.a.email)) && (await apiLogin(api, saved.b.email))) return saved;
    }
    const accounts = { a: await createAccount(api, "a"), b: await createAccount(api, "b") };
    writeFileSync(ACCOUNTS_FILE, JSON.stringify(accounts, null, 2));
    return accounts;
  } finally {
    await api.dispose();
  }
}

/** A signed-in API client for arranging test data. */
export async function apiAs(account: Account): Promise<APIRequestContext> {
  const anon = await request.newContext();
  const tokens = await apiLogin(anon, account.email);
  await anon.dispose();
  if (!tokens) throw new Error(`cannot log in ${account.email}`);
  return request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${tokens.access}` } });
}

/** A browser context signed in as `account` (tokens seeded, skipping the login form). */
export async function pageAs(browser: Browser, account: Account): Promise<Page> {
  const anon = await request.newContext();
  const tokens = await apiLogin(anon, account.email);
  await anon.dispose();
  if (!tokens) throw new Error(`cannot log in ${account.email}`);
  const context = await browser.newContext({ baseURL: "http://127.0.0.1:5173" });
  await context.addInitScript(
    ([access, refresh]) => {
      if (localStorage.getItem("e2e.seeded")) return;
      localStorage.setItem("e2e.seeded", "1");
      localStorage.setItem("tara.access", access);
      localStorage.setItem("tara.refresh", refresh);
    },
    [tokens.access, tokens.refresh],
  );
  return context.newPage();
}

/** Fail the test on anything that looks like a raw account id in visible text. */
export async function expectNoUuid(page: Page) {
  const text = await page.locator("body").innerText();
  expect(text).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/i);
  expect(text).not.toMatch(/\b01[0-9a-f]{6}\b/i);
}

export async function dmWith(api: APIRequestContext, otherId: string): Promise<string> {
  const res = await api.post(`${API}/conversations/`, { data: { type: "dm", other_id: otherId } });
  expect(res.ok()).toBe(true);
  return (await res.json()).data.id;
}
