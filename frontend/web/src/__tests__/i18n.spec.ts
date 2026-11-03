import { baseCompile } from "@intlify/message-compiler";
import { describe, expect, it } from "vitest";

import ar from "@/i18n/ar";
import en from "@/i18n/en";

function keys(node: object, prefix = ""): string[] {
  return Object.entries(node).flatMap(([k, v]) =>
    typeof v === "object" && v ? keys(v, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

function messages(node: object, prefix = ""): Array<[string, string]> {
  return Object.entries(node).flatMap(([k, v]): Array<[string, string]> =>
    typeof v === "object" && v ? messages(v, `${prefix}${k}.`) : typeof v === "string" ? [[`${prefix}${k}`, v]] : [],
  );
}

/** Messages vue-i18n cannot compile. They throw at render time and blank the page. */
function invalid(locale: object): string[] {
  return messages(locale).flatMap(([key, text]) => {
    const errors: string[] = [];
    baseCompile(text, { onError: (e) => errors.push(`${key}: ${e.message} in ${JSON.stringify(text)}`) });
    return errors;
  });
}

describe("translations", () => {
  it("ar and en have the same keys", () => {
    expect(keys(ar).sort()).toEqual(keys(en).sort());
  });

  // A literal "@", "{", "}" or "|" must be written as {'@'} etc.
  it.each([
    ["ar", ar],
    ["en", en],
  ])("every %s message compiles", (_name, locale) => {
    expect(invalid(locale)).toEqual([]);
  });
});
