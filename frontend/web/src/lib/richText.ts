// Splits user text into plain runs, links, #tags and @mentions. The patterns match
// the server's (services/post/posts/services.py and linkpreview.py).

export type RichToken =
  | { kind: "text"; text: string }
  | { kind: "link"; text: string; href: string }
  | { kind: "tag"; text: string; tag: string }
  | { kind: "mention"; text: string; handle: string };

const PATTERN =
  /(https?:\/\/[^\s<>"'()]+)|(?<![\p{L}\p{N}_/&#])#([\p{L}\p{N}_]{1,80})|(?<![\p{L}\p{N}_.@/])@([a-zA-Z0-9_]{3,30})/gu;
const TRAILING_PUNCTUATION = /[.,;:!?،؛؟]+$/;

export function tokenize(body: string): RichToken[] {
  const tokens: RichToken[] = [];
  let last = 0;
  const pushText = (text: string) => {
    const previous = tokens.at(-1);
    if (!text) return;
    if (previous?.kind === "text") previous.text += text;
    else tokens.push({ kind: "text", text });
  };
  for (const match of body.matchAll(PATTERN)) {
    pushText(body.slice(last, match.index));
    last = match.index + match[0].length;
    if (match[1]) {
      const href = match[1].replace(TRAILING_PUNCTUATION, "");
      tokens.push({ kind: "link", text: href, href });
      pushText(match[1].slice(href.length));
    } else if (match[2]) {
      tokens.push({ kind: "tag", text: match[0], tag: match[2] });
    } else {
      tokens.push({ kind: "mention", text: match[0], handle: match[3] });
    }
  }
  pushText(body.slice(last));
  return tokens;
}

/** The @word being typed just before the caret, if any. */
export function mentionAtCaret(text: string, caret: number): { query: string; start: number } | null {
  const match = /(?:^|[\s(])@([a-zA-Z0-9_]{1,30})$/.exec(text.slice(0, caret));
  if (!match) return null;
  return { query: match[1], start: caret - match[1].length - 1 };
}

export function hasLink(body: string): boolean {
  return tokenize(body).some((t) => t.kind === "link");
}
