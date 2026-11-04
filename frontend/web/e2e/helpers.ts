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

/** Legal versions the server accepts (identity's LEGAL_*_VERSION settings). */
export const LEGAL_VERSION = "2026-11-04-draft";

/**
 * A complete POST /auth/register/ body (plan 08, track 1D). The display name is
 * built from first and last name, so `${first} ${last}` is the account's name.
 */
export function signupData(email: string, handle: string, first: string, last: string, extra: object = {}) {
  return {
    email,
    handle,
    first_name: first,
    last_name: last,
    password: PASSWORD,
    password_confirm: PASSWORD,
    date_of_birth: "1994-05-20",
    accept_terms: true,
    terms_version: LEGAL_VERSION,
    privacy_version: LEGAL_VERSION,
    language: "ar",
    ...extra,
  };
}

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
  const first = slot === "a" ? "ليلى" : "Omar";
  const name = `${first} ${tag}`;
  const res = await api.post(`${API}/auth/register/`, { data: signupData(email, handle, first, tag) });
  expect(res.status(), await res.text()).toBe(201);
  const token = await verificationToken(api, email);
  expect((await api.post(`${API}/auth/verify-email/`, { data: { token } })).ok()).toBe(true);
  const { data } = await res.json();
  return { email, handle, name, id: data.account_id };
}

/**
 * Three long-lived accounts. Registration is limited to 10 an hour per IP, so
 * they are kept in e2e/.accounts.json between runs and only recreated when gone.
 */
export async function sharedAccounts(): Promise<{ a: Account; b: Account; c: Account }> {
  const api = await request.newContext();
  try {
    const saved = existsSync(ACCOUNTS_FILE) ? JSON.parse(readFileSync(ACCOUNTS_FILE, "utf8")) : {};
    const usable = async (slot: string): Promise<Account> =>
      saved[slot] && (await apiLogin(api, saved[slot].email)) ? saved[slot] : createAccount(api, slot);
    const accounts = { a: await usable("a"), b: await usable("b"), c: await usable("c") };
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

/** The SPA under test: the Vite dev server, or `vite preview` of the build. */
export const BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173";

/** A browser context signed in as `account` (tokens seeded, skipping the login form). */
export async function pageAs(
  browser: Browser,
  account: Account,
  baseURL = BASE_URL,
  serviceWorkers: "allow" | "block" = "allow",
): Promise<Page> {
  const anon = await request.newContext();
  const tokens = await apiLogin(anon, account.email);
  await anon.dispose();
  if (!tokens) throw new Error(`cannot log in ${account.email}`);
  const context = await browser.newContext({ baseURL, serviceWorkers });
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

export interface RegisterFields {
  first: string;
  last: string;
  handle: string;
  email: string;
  password?: string;
  confirm?: string;
  /** [day, month, year] as the selects' values. */
  dob?: [string, string, string];
  consent?: boolean;
}

/** Labels of the sign-up form (track 1D), per language. */
export const REGISTER_LABELS = {
  ar: {
    first: "الاسم الأول",
    last: "اسم العائلة",
    handle: "اسم المستخدم",
    email: "البريد الإلكتروني",
    password: "كلمة المرور",
    confirm: "تأكيد كلمة المرور",
    day: "اليوم",
    month: "الشهر",
    year: "السنة",
    consent: /أوافق على/,
    submit: "تسجيل",
  },
  en: {
    first: "First name",
    last: "Last name",
    handle: "Username",
    email: "Email",
    password: "Password",
    confirm: "Confirm password",
    day: "Day",
    month: "Month",
    year: "Year",
    consent: /I agree to/,
    submit: "Sign up",
  },
} as const;

/** Fill the sign-up form on /register (doesn't submit). */
export async function fillRegisterForm(page: Page, fields: RegisterFields, lang: "ar" | "en" = "ar") {
  const l = REGISTER_LABELS[lang];
  await page.getByLabel(l.first, { exact: true }).fill(fields.first);
  await page.getByLabel(l.last, { exact: true }).fill(fields.last);
  await page.getByLabel(l.handle, { exact: true }).fill(fields.handle);
  await page.getByLabel(l.email, { exact: true }).fill(fields.email);
  await page.getByLabel(l.password, { exact: true }).fill(fields.password ?? PASSWORD);
  await page.getByLabel(l.confirm, { exact: true }).fill(fields.confirm ?? fields.password ?? PASSWORD);
  const [day, month, year] = fields.dob ?? ["20", "5", "1994"];
  await page.getByLabel(l.day, { exact: true }).selectOption(day);
  await page.getByLabel(l.month, { exact: true }).selectOption(month);
  await page.getByLabel(l.year, { exact: true }).selectOption(year);
  if (fields.consent ?? true) await page.getByLabel(l.consent).check();
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

/** Make two accounts friends. Either side may already have a pending request. */
export async function befriend(one: Account, other: Account) {
  const a = await apiAs(one);
  const friends = (await (await a.get(`${API}/friends/`)).json()).data.friends as string[];
  if (friends.includes(other.id)) return;
  await a.post(`${API}/friends/requests/`, { data: { to_user_id: other.id } });
  const b = await apiAs(other);
  for (const [client, sender] of [[b, one], [a, other]] as const) {
    const rows = (await (await client.get(`${API}/friends/requests/`)).json()).data as { id: string; requested_by: string }[];
    const row = rows.find((r) => r.requested_by === sender.id);
    if (row) await client.post(`${API}/friends/requests/${row.id}/accept/`);
  }
}

export async function unfriend(one: Account, other: Account) {
  await (await apiAs(one)).delete(`${API}/friends/${other.id}/`);
}

/**
 * Show this page in `lang` without changing the (shared) account. Since the
 * settings centre, the account's language wins over `tara.locale` on every
 * boot, so the page's own GET /me/ is answered with `lang`; nothing is saved.
 */
export async function useLocale(page: Page, lang: "ar" | "en") {
  await page.addInitScript((l) => localStorage.setItem("tara.locale", l), lang);
  await page.route(/\/api\/v1\/me\/(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const res = await route.fetch();
    const body = await res.json().catch(() => null);
    if (!body?.data) return route.fulfill({ response: res });
    await route.fulfill({ response: res, json: { ...body, data: { ...body.data, language: lang } } });
  });
}
