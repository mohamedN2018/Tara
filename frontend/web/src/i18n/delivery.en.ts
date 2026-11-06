// Feed delivery states (Tara Intelligence 08 §7.7, WP 4c.4-B3). Merged into en.ts as `delivery`.
export default {
  loading: "Loading posts",
  loadingMore: "Loading more posts",
  retry: {
    title: "Couldn't load, try again",
    hint: "Check your connection and try again.",
    action: "Try again",
    retrying: "Trying again…",
  },
  end: {
    title: "You're all caught up",
    hint: "No new posts right now. There's more to discover.",
    explore: "Explore",
    reels: "Reels",
  },
  snapshot: {
    label: "Post loading",
  },
};
