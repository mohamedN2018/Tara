// Social shell (wave 2, social-shell track): Friends home, birthdays, group
// search and last activity, and the notifications dropdown's sections. Wired
// into en.ts as `socialShell`.
export default {
  friends: {
    home: "Home",
    birthdays: "Birthdays",
    requestsTitle: "Friend requests",
    pymkTitle: "People you may know",
    seeAll: "See all",
    homeEmpty: "No friend requests or suggestions right now.",
  },
  birthdays: {
    title: "Birthdays",
    today: "Today's birthdays",
    upcoming: "This week",
    none: "None of your friends has a birthday this week.",
    privacyNote: "Only friends who share their birthday with friends show here, as day and month only.",
    railOne: "{name} has a birthday today.",
    railTwo: "{name} and {other} have birthdays today.",
    railMany: "{name} and {count} other friends have birthdays today.",
    todayBadge: "Today",
    tomorrow: "Tomorrow",
    message: "Message",
    messageName: "Message {name}",
  },
  groups: {
    searchYours: "Search your groups",
    noMatch: "No matching groups.",
    lastActive: "Last active {time}",
    noPostsYet: "No posts yet",
    viewGroup: "View group",
  },
  notifications: {
    filter: "Filter notifications",
    new: "New",
    earlier: "Earlier",
    seePrevious: "See previous notifications",
  },
};
