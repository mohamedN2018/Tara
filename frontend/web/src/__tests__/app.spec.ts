import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ar from "@/i18n/ar";
import en from "@/i18n/en";
import { arabicPlural, i18n } from "@/i18n";
import { errorKey, errorMessage } from "@/lib/errors";
import { safeRedirect } from "@/lib/redirect";
import { notificationService } from "@/services/notification";
import { useNotificationStore } from "@/stores/notifications";

function flatten(node: object, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(node)) {
    if (typeof value === "string") out[prefix + key] = value;
    else Object.assign(out, flatten(value, `${prefix}${key}.`));
  }
  return out;
}

const flatEn = flatten(en);
const flatAr = flatten(ar);
const placeholders = (text: string) => [...new Set(text.match(/\{\w+\}/g) ?? [])].sort();

describe("translations", () => {
  it("ar and en have exactly the same keys", () => {
    expect(Object.keys(flatAr).sort()).toEqual(Object.keys(flatEn).sort());
  });

  it("use the same placeholders", () => {
    for (const [key, text] of Object.entries(flatEn)) {
      if (text.includes(" | ")) continue; // Arabic spells out zero/one/two.
      expect(placeholders(flatAr[key]), key).toEqual(placeholders(text));
    }
  });

  it("Arabic plurals have all six forms, English two", () => {
    for (const [key, text] of Object.entries(flatEn)) {
      if (!text.includes(" | ")) continue;
      expect(text.split(" | "), key).toHaveLength(2);
      expect(flatAr[key].split(" | "), key).toHaveLength(6);
    }
  });
});

describe("arabicPlural", () => {
  it.each([
    [0, 0],
    [1, 1],
    [2, 2],
    [3, 3],
    [10, 3],
    [11, 4],
    [99, 4],
    [100, 5],
    [101, 5],
    [102, 5],
    [103, 3],
    [111, 4],
    [1000, 5],
  ])("%i uses form %i", (count, form) => expect(arabicPlural(count)).toBe(form));

  it("renders through vue-i18n", () => {
    const t = i18n.global.t;
    i18n.global.locale.value = "ar";
    expect(t("post.commentsCount", 2)).toBe("تعليقان");
    expect(t("post.commentsCount", 5)).toBe("5 تعليقات");
    expect(t("post.commentsCount", 15)).toBe("15 تعليقًا");
    expect(t("post.commentsCount", 100)).toBe("100 تعليق");
    i18n.global.locale.value = "en";
    expect(t("post.commentsCount", 1)).toBe("1 comment");
    expect(t("post.commentsCount", 2)).toBe("2 comments");
  });
});

describe("error codes", () => {
  it("every mapped code has a translation", () => {
    for (const code of ["conflict", "rate_limited", "network_error", "server_error", "nonsense"]) {
      expect(flatEn[errorKey(code)], code).toBeTruthy();
    }
  });

  it("translates by code, with per-screen overrides", () => {
    i18n.global.locale.value = "en";
    const failure = { response: { status: 404, data: { error: { code: "not_found", message: "raw" } } } };
    expect(errorMessage(failure)).toBe(en.errors.not_found);
    expect(errorMessage(failure, { not_found: "states.notFound" })).toBe(en.states.notFound);
  });
});

describe("safeRedirect", () => {
  it.each(["/home", "/u/id/123?tab=photos", "/messages/abc"])("allows %s", (path) => {
    expect(safeRedirect(path)).toBe(path);
  });

  it.each(["//evil.example", "/\\evil.example", "/\t/evil.example", "/\n/evil.example", "https://evil.example", "javascript:alert(1)", "home", "", undefined, null, ["/a"]])(
    "rejects %j",
    (path) => expect(safeRedirect(path)).toBe("/home"),
  );
});

describe("notification store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("reads the count", async () => {
    vi.spyOn(notificationService, "unreadCount").mockResolvedValue(4);
    const store = useNotificationStore();
    await store.refresh();
    expect(store.unread).toBe(4);
  });

  it.each([undefined, NaN, null, "x", -1])("ignores a bad count (%s)", async (bad) => {
    vi.spyOn(notificationService, "unreadCount").mockResolvedValue(bad as unknown as number);
    const store = useNotificationStore();
    store.unread = 2;
    await store.refresh();
    expect(store.unread).toBe(2);
  });
});
