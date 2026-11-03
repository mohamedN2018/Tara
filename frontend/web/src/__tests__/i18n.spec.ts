import { describe, expect, it } from "vitest";

import ar from "@/i18n/ar";
import en from "@/i18n/en";

function keys(node: object, prefix = ""): string[] {
  return Object.entries(node).flatMap(([k, v]) =>
    typeof v === "object" && v ? keys(v, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

describe("translations", () => {
  it("ar and en have the same keys", () => {
    expect(keys(ar).sort()).toEqual(keys(en).sort());
  });
});
