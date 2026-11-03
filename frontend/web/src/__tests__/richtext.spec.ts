import { describe, expect, it } from "vitest";

import { hasLink, mentionAtCaret, tokenize } from "@/lib/richText";

describe("tokenize", () => {
  it("finds tags, mentions and links, keeping all the text", () => {
    const body = "hi @nadia_1 see #مرحبا at https://a.example/x, ok";
    const tokens = tokenize(body);
    expect(tokens.map((t) => t.text).join("")).toBe(body);
    expect(tokens.filter((t) => t.kind !== "text")).toEqual([
      { kind: "mention", text: "@nadia_1", handle: "nadia_1" },
      { kind: "tag", text: "#مرحبا", tag: "مرحبا" },
      { kind: "link", text: "https://a.example/x", href: "https://a.example/x" },
    ]);
  });

  it("ignores emails, url fragments and tags inside words", () => {
    const tokens = tokenize("me@host.com x#no https://a.b/#frag");
    expect(tokens.filter((t) => t.kind === "mention" || t.kind === "tag")).toEqual([]);
  });

  it("never turns other schemes into links", () => {
    expect(tokenize("javascript:alert(1) data:text/html,x").every((t) => t.kind === "text")).toBe(true);
  });

  it("detects links", () => {
    expect(hasLink("see https://a.example")).toBe(true);
    expect(hasLink("no link")).toBe(false);
  });
});

describe("mentionAtCaret", () => {
  it("finds the word being typed", () => {
    expect(mentionAtCaret("hi @na", 6)).toEqual({ query: "na", start: 3 });
    expect(mentionAtCaret("@na", 3)).toEqual({ query: "na", start: 0 });
  });

  it("ignores emails and finished words", () => {
    expect(mentionAtCaret("me@host", 7)).toBeNull();
    expect(mentionAtCaret("hi @na ", 7)).toBeNull();
  });
});
