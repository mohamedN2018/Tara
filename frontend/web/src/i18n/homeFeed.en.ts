// Home feed and post card (plan 08, track 2B). Merged into en.ts as `homeFeed`.
export default {
  undo: "Undo",
  modes: {
    label: "Sort the feed",
    for_you: "For you",
    recent: "Latest",
    favorites: "Favorites",
    following: "Following",
  },
  hide: {
    action: "Hide post",
    title: "Post hidden",
    hint: "You won't see this post in your feed.",
    why: "Why don't you want to see this?",
    reasons: {
      notInterested: "Not interested",
      spam: "Spam or scam",
      sexual: "Sexual content",
      annoying: "Annoying",
      dislikeCreator: "I don't like the creator",
      other: "Something else",
    },
    thanks: "Thanks. Your feedback helps improve your feed.",
    otherSteps: "Other steps you can take",
    snooze: "Snooze {name} for 30 days",
    snoozed: "You won't see posts from {name} for 30 days.",
  },
  comments: {
    preview: "Top comments",
  },
  ad: {
    hide: "Hide ad",
    hidden: "Ad hidden",
    hiddenHint: "You won't see this ad again during this session.",
  },
  emoji: {
    open: "Insert emoji",
    label: "Emoji",
  },
};
