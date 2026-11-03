// Reaction catalogue — mirrors the backend REACTION_TYPES
// (services/post/posts/models.py: like, love, care, haha, wow, sad, angry).
// Emoji-based so it needs no extra assets and renders correctly in RTL.

export interface ReactionDef {
  key: string;
  emoji: string;
  labelKey: string; // i18n key under `reactionTypes`
  color: string; // Tailwind text color for the active state
}

export const REACTIONS: ReactionDef[] = [
  { key: "like", emoji: "👍", labelKey: "reactionTypes.like", color: "text-brand-600 dark:text-brand-300" },
  { key: "love", emoji: "❤️", labelKey: "reactionTypes.love", color: "text-accent-500" },
  { key: "care", emoji: "🤗", labelKey: "reactionTypes.care", color: "text-amber-500" },
  { key: "haha", emoji: "😆", labelKey: "reactionTypes.haha", color: "text-amber-500" },
  { key: "wow", emoji: "😮", labelKey: "reactionTypes.wow", color: "text-amber-500" },
  { key: "sad", emoji: "😢", labelKey: "reactionTypes.sad", color: "text-amber-500" },
  { key: "angry", emoji: "😡", labelKey: "reactionTypes.angry", color: "text-orange-600" },
];

// services/chat/chat/models.py has no "care".
export const MESSAGE_REACTIONS = REACTIONS.filter((r) => r.key !== "care");

export function reactionByKey(key: string | null | undefined): ReactionDef | undefined {
  if (!key) return undefined;
  return REACTIONS.find((r) => r.key === key);
}
