/** The comment box's emoji grid: a small built-in set, no library or remote assets. */
export const EMOJIS = [
  "😀", "😂", "🥰", "😍", "😊", "😉", "😎", "🤩",
  "🤔", "😅", "😢", "😭", "😡", "😮", "😴", "🙏",
  "👍", "👏", "🙌", "💪", "🤝", "👌", "✌️", "🔥",
  "❤️", "💜", "💯", "🎉", "✨", "🌹", "☕", "🌙",
] as const;

/** `value` with `text` put in place of the selection [start, end), and the caret after it. */
export function insertAt(value: string, text: string, start: number, end = start): { value: string; caret: number } {
  const from = Math.max(0, Math.min(start, value.length));
  const to = Math.max(from, Math.min(end, value.length));
  return { value: value.slice(0, from) + text + value.slice(to), caret: from + text.length };
}
