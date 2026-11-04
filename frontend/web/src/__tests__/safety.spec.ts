// Track T7: moderator console, Support inbox, suspended sign-in, notification
// sentences for account status and client feature flags.
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApp, defineComponent, h, type App } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import { MENU_CATALOG, isVisible, setFlaggedOff } from "@/components/layout/menuCatalog";
import { notificationText } from "@/components/notifications/kinds";
import SuspendedNotice from "@/components/moderation/SuspendedNotice.vue";
import { i18n, setLocale } from "@/i18n";
import { useSafetyLabels } from "@/lib/safetyLabels";
import { adminService, caseActions, targetLink } from "@/services/admin";
import { moderationService, ownTargetLink, reportReason, suspensionFrom } from "@/services/moderation";
import { bucket, flagOn, hiddenMenuItems } from "@/stores/flags";
import { useAuthStore } from "@/stores/auth";
import type { Notification } from "@/types";

vi.mock("@/components/layout/AppShell.vue", () => ({
  default: defineComponent({ props: ["right", "left"], setup: (_p, { slots }) => () => h("div", slots.default?.()) }),
}));
vi.mock("@/components/admin/AdminLayout.vue", () => ({
  default: defineComponent({ props: ["title", "subtitle"], setup: (_p, { slots }) => () => h("div", slots.default?.()) }),
}));

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const Blank = { render: () => null };
let app: App | null = null;
let host: HTMLElement;

async function mount(component: unknown, props: Record<string, unknown> = {}, setup?: () => void, path = "/") {
  const pinia = createPinia();
  setActivePinia(pinia);
  setup?.();
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:p(.*)*", component: Blank }] });
  await router.push(path);
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp(component as never, props);
  app.use(pinia).use(router).use(i18n);
  app.mount(host);
  await flush();
  await flush();
}

const axiosError = (code: string, details: unknown[] = []) => ({ response: { status: 403, data: { error: { code, message: "", details } } } });

beforeEach(() => setLocale("en"));
afterEach(() => {
  app?.unmount();
  app = null;
  host?.remove();
  vi.restoreAllMocks();
  setFlaggedOff([]);
});

describe("suspended sign-in", () => {
  it("reads until when and who decided from account_suspended", () => {
    const until = "2026-12-01T10:00:00+00:00";
    expect(
      suspensionFrom(
        axiosError("account_suspended", [
          { field: "until", code: "suspended_until", message: until },
          { field: "source", code: "moderation", message: "" },
        ]),
      ),
    ).toEqual({ until, source: "moderation" });
    expect(suspensionFrom(axiosError("account_suspended", [{ field: "until", code: "suspended_until", message: "" }]))?.until).toBeNull();
    expect(suspensionFrom(axiosError("permission_denied"))).toBeNull();
  });

  it("shows the end date in Arabic and links the standards", async () => {
    setLocale("ar");
    await mount(SuspendedNotice, { suspension: { until: "2026-12-01T10:00:00Z", source: "moderation" } });
    const text = host.textContent ?? "";
    expect(text).toContain("حسابك موقوف");
    expect(text).toContain("معايير المجتمع");
    expect(host.querySelector('a[href="/legal/community-standards"]')).not.toBeNull();
  });
});

describe("case actions and links", () => {
  it("mirror the server: a profile cannot be removed, a story can", () => {
    expect(caseActions("user")).not.toContain("remove");
    expect(caseActions("user")).toContain("restrict");
    expect(caseActions("story")).toContain("remove");
    expect(caseActions("page")).toEqual(["remove", "restrict", "warn", "dismiss"]);
    expect(caseActions("unknown")).toEqual(["dismiss"]);
  });

  it("link targets that have a page and leave the rest as ids", () => {
    expect(targetLink("page", "p1")).toBe("/pages/id/p1");
    // The public profile: every moderator may open it (the console needs admin.users.view).
    expect(targetLink("user", "u1")).toBe("/u/id/u1");
    expect(targetLink("message", "m1")).toBeNull();
    expect(ownTargetLink("user", "u1")).toBeNull();
    expect(ownTargetLink("post", "a/b")).toBe("/posts/a%2Fb");
  });

  it("store a reason code with the reporter's words, bounded", () => {
    expect(reportReason("spam", "  buy now  ")).toBe("spam: buy now");
    expect(reportReason("other", "x".repeat(400))).toHaveLength(200);
  });
});

describe("reason labels", () => {
  it("name known codes and keep free text as the reporter's words", async () => {
    let labels!: ReturnType<typeof useSafetyLabels>;
    await mount(defineComponent({ setup: () => ((labels = useSafetyLabels()), () => null) }));
    expect(labels.reasonLabel("scam: wants my card")).toBe("Scam or fraud");
    expect(labels.reasonDetail("scam: wants my card")).toBe("wants my card");
    expect(labels.reasonLabel("he keeps insulting me")).toBe("In their words");
    expect(labels.reasonDetail("he keeps insulting me")).toBe("he keeps insulting me");
    expect(labels.targetLabel("listing_review")).toBe("Seller review");
  });
});

describe("account status notifications", () => {
  const t = i18n.global.t as never;
  const te = i18n.global.te as never;
  const row = (kind: string, data: Record<string, string>, body = "fixed english"): Notification =>
    ({ id: "n1", kind, actor_id: null, subject_ref: "case:c1", body, data, read_at: null, created_at: "" }) as Notification;

  it("say what was decided, in the reader's language", () => {
    expect(notificationText(row("moderation.decision", { decision: "remove", target_type: "post" }), t, te, "")).toContain("removed your Post");
    expect(notificationText(row("moderation.appeal", { status: "overturned", target_type: "listing" }), t, te, "")).toContain("overturned");
    setLocale("ar");
    expect(notificationText(row("moderation.decision", { decision: "warn", target_type: "comment" }), t, te, "")).toContain("تحذير");
  });

  it("show a notice as the staff wrote it", () => {
    expect(notificationText(row("system.notice", {}, "Please update your page."), t, te, "")).toBe("Please update your page.");
  });
});

describe("feature flags", () => {
  it("bucket an account the same way every time, and roll out by percentage", () => {
    expect(bucket("acct-1", "ui.marketplace")).toBe(bucket("acct-1", "ui.marketplace"));
    expect(bucket("acct-1", "k")).toBeGreaterThanOrEqual(0);
    expect(bucket("acct-1", "k")).toBeLessThan(100);
    expect(flagOn({ key: "k", enabled: false, rollout_pct: 100 }, "a")).toBe(false);
    expect(flagOn({ key: "k", enabled: true, rollout_pct: 100 }, "a")).toBe(true);
    expect(flagOn({ key: "k", enabled: true, rollout_pct: 0 }, "a")).toBe(false);
  });

  it("hide a menu destination its ui.<id> flag turns off, never a staff item", () => {
    const flags = {
      "ui.marketplace": { key: "ui.marketplace", enabled: false, rollout_pct: 100 },
      "ui.admin": { key: "ui.admin", enabled: false, rollout_pct: 100 },
    };
    const hidden = hiddenMenuItems(flags, "a");
    expect(hidden).toContain("marketplace");
    expect(hidden).not.toContain("admin");
    setFlaggedOff(hidden);
    const market = MENU_CATALOG.find((i) => i.id === "marketplace")!;
    expect(isVisible(market, new Set(), "personal")).toBe(false);
    setFlaggedOff([]);
    expect(isVisible(market, new Set(), "personal")).toBe(true);
  });

  it("show the Support inbox and the Community Standards to every member", () => {
    for (const id of ["support", "communityStandards"]) {
      const item = MENU_CATALOG.find((i) => i.id === id)!;
      expect(isVisible(item, new Set(), "personal")).toBe(true);
    }
  });
});

describe("moderation console", () => {
  const openCase = {
    id: "c1",
    target_type: "user",
    target_id: "u1",
    severity: "normal",
    state: "open",
    report_count: 2,
    assigned_to: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  async function mountConsole(caps: string[], path = "/admin/moderation") {
    const View = (await import("@/views/AdminModerationView.vue")).default;
    await mount(View, {}, () => {
      const auth = useAuthStore();
      auth.capabilities = new Set(caps);
      auth.account = { id: "me" } as never;
    }, path);
  }

  it("claims an open case and offers only the actions its target allows", async () => {
    const cases = vi.spyOn(adminService, "cases").mockResolvedValue({ data: [openCase], page: { next_cursor: null, prev_cursor: null, has_more: false } });
    const assign = vi.spyOn(adminService, "assignCase").mockResolvedValue({ ...openCase, state: "in_review", assigned_to: "me" });
    await mountConsole(["moderation.case.view", "moderation.case.act"]);
    expect(cases).toHaveBeenCalledWith({ state: "open" });
    expect(host.querySelectorAll('[data-testid="mod-case"]')).toHaveLength(1);
    expect(host.querySelector('[data-testid="mod-tab-appeals"]')).toBeNull();

    (host.querySelector('[data-testid="mod-decide"]') as HTMLButtonElement).click();
    await flush();
    const options = [...document.querySelectorAll('[data-testid^="decision-"][type="radio"]')].map((e) => (e as HTMLInputElement).value);
    expect(options).toEqual(["restrict", "shadow", "warn", "dismiss"]);
    (document.querySelector('[data-testid="case-decision-dialog"] button[aria-label]') as HTMLButtonElement).click();
    await flush();

    (host.querySelector('[data-testid="mod-claim"]') as HTMLButtonElement).click();
    await flush();
    expect(assign).toHaveBeenCalledWith("c1");
    expect(host.querySelectorAll('[data-testid="mod-case"]')).toHaveLength(0);
  });

  it("sends the decision with the reason for the owner", async () => {
    vi.spyOn(adminService, "cases").mockResolvedValue({ data: [{ ...openCase, target_type: "post" }], page: { next_cursor: null, prev_cursor: null, has_more: false } });
    const act = vi.spyOn(adminService, "actionCase").mockResolvedValue();
    await mountConsole(["moderation.case.view", "moderation.case.act"]);
    (host.querySelector('[data-testid="mod-decide"]') as HTMLButtonElement).click();
    await flush();
    (document.querySelector('[data-testid="decision-remove"]') as HTMLInputElement).click();
    const reason = document.querySelector('[data-testid="decision-reason"]') as HTMLTextAreaElement;
    reason.value = "Spam links";
    reason.dispatchEvent(new Event("input"));
    await flush();
    (document.querySelector('[data-testid="decision-confirm"]') as HTMLButtonElement).click();
    await flush();
    expect(act).toHaveBeenCalledWith("c1", "remove", "Spam links");
    expect(host.querySelectorAll('[data-testid="mod-case"]')).toHaveLength(0);
  });

  it("reviewers without act see no claim or decide buttons; appeals need their own capability", async () => {
    vi.spyOn(adminService, "cases").mockResolvedValue({ data: [openCase], page: { next_cursor: null, prev_cursor: null, has_more: false } });
    const appeals = vi.spyOn(adminService, "appeals").mockResolvedValue({ data: [], page: { next_cursor: null, prev_cursor: null, has_more: false } });
    await mountConsole(["moderation.case.view", "moderation.appeal.view"], "/admin/moderation?tab=appeals&status=overturned");
    expect(appeals).toHaveBeenCalledWith("overturned");
    expect(host.querySelector('[data-testid="mod-appeals"]')).not.toBeNull();
  });
});

describe("Support inbox", () => {
  it("lists my decisions and sends a review request once", async () => {
    vi.spyOn(moderationService, "myCases").mockResolvedValue({
      data: [
        {
          id: "c9",
          target_type: "post",
          target_id: "p9",
          decision: "remove",
          reason: "Spam links",
          decided_at: new Date().toISOString(),
          appeal_status: null,
          appealed_at: null,
          can_appeal: true,
        },
      ],
      page: { next_cursor: null, prev_cursor: null, has_more: false },
    });
    const appeal = vi.spyOn(moderationService, "appeal").mockResolvedValue();
    const View = (await import("@/views/SupportView.vue")).default;
    await mount(View, {}, undefined, "/support?case=c9");
    expect(host.textContent).toContain("We removed your Post");
    expect(host.textContent).toContain("Spam links");
    (document.querySelector('[data-testid="support-request-review"]') as HTMLButtonElement).click();
    await flush();
    const box = document.querySelector('[data-testid="appeal-text"]') as HTMLTextAreaElement;
    box.value = "It was my own shop link.";
    box.dispatchEvent(new Event("input"));
    await flush();
    (document.querySelector('[data-testid="appeal-send"]') as HTMLButtonElement).click();
    await flush();
    expect(appeal).toHaveBeenCalledWith("c9", "It was my own shop link.");
    expect(document.querySelector('[data-testid="support-request-review"]')).toBeNull();
  });
});
