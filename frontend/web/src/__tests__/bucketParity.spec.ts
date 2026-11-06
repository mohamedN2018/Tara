// Tara Intelligence WP 5.4: the web's flag bucket and every service's
// `tara_common.bucketing.bucket` are one function (FNV-1a over UTF-16 code units of
// "account:key", % 100). The shared fixture is checked into the feed suite too.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { bucket } from "@/stores/flags";

interface Fixture {
  fold: number;
  cases: { account_id: string; key: string; expected: number }[];
}

const path = resolve(__dirname, "../../../../services/feed/intel/tests/fixtures/bucket_parity.json");
const fixture = JSON.parse(readFileSync(path, "utf8")) as Fixture;

describe("bucket parity with tara_common.bucketing (WP 5.4)", () => {
  it("uses the % 100 fold and has enough rows to mean something", () => {
    expect(fixture.fold).toBe(100);
    expect(fixture.cases.length).toBeGreaterThanOrEqual(20);
  });

  it("matches every fixture row", () => {
    const wrong = fixture.cases.filter((c) => bucket(c.account_id, c.key) !== c.expected);
    expect(wrong).toEqual([]);
  });

  it("covers non-ASCII keys (UTF-16 code units, not bytes)", () => {
    expect(fixture.cases.some((c) => [...c.key].some((ch) => ch.charCodeAt(0) > 0x7f))).toBe(true);
  });
});
