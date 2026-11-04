import { Globe, Lock, type LucideIcon, UserCheck, Users, UsersRound } from "lucide-vue-next";

/** Who can see a post outside a group (the server's Audience values, minus `group`). */
export const AUDIENCES: { v: string; icon: LucideIcon; label: string }[] = [
  { v: "public", icon: Globe, label: "feed.audiencePublic" },
  { v: "friends", icon: Users, label: "feed.audienceFriends" },
  { v: "followers", icon: UserCheck, label: "feed.audienceFollowers" },
  { v: "only_me", icon: Lock, label: "feed.audienceOnlyMe" },
];

export const AUDIENCE_ICON: Record<string, LucideIcon> = {
  public: Globe,
  friends: Users,
  followers: UserCheck,
  only_me: Lock,
  group: UsersRound,
};

/** The i18n key naming an audience (`group` included). */
export function audienceLabel(audience: string): string {
  if (audience === "group") return "feed.audienceGroup";
  return AUDIENCES.find((a) => a.v === audience)?.label ?? "feed.audiencePublic";
}
