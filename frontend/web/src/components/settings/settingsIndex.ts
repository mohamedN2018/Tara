// Every setting the settings centre has, as a searchable entry: where it lives
// (a section, and the anchor of its card) and words people may search it by.
// Titles and keywords are i18n (`polish.settings.entries.<key>`), so a search
// works in the reader's language. Only real, existing cards are listed.
import {
  Ban,
  Bell,
  Cake,
  EyeOff,
  History,
  KeyRound,
  Languages,
  ListFilter,
  Lock,
  type LucideIcon,
  MessageCircle,
  Monitor,
  Moon,
  Palette,
  Search,
  ShieldCheck,
  Smartphone,
  Tag,
  Trash2,
  UserRound,
  Users,
} from "lucide-vue-next";

import { foldText } from "@/components/layout/menuCatalog";

export interface SettingsEntry {
  key: string;
  to: string;
  icon: LucideIcon;
}

export const SETTINGS_ENTRIES: SettingsEntry[] = [
  { key: "personal", to: "/settings/account#personal-details", icon: UserRound },
  { key: "birthday", to: "/settings/account#personal", icon: Cake },
  { key: "profileBasics", to: "/settings/account#profile-basics", icon: UserRound },
  { key: "deactivate", to: "/settings/account#deactivate", icon: EyeOff },
  { key: "delete", to: "/settings/account#delete", icon: Trash2 },
  { key: "profilePrivacy", to: "/settings/privacy#profile", icon: Lock },
  { key: "searchability", to: "/settings/privacy#search", icon: Search },
  { key: "messaging", to: "/settings/privacy#messaging", icon: MessageCircle },
  { key: "connections", to: "/settings/privacy#relationships", icon: Users },
  { key: "tags", to: "/settings/privacy#tags", icon: Tag },
  { key: "activeStatus", to: "/settings/privacy#active-status", icon: Monitor },
  { key: "password", to: "/settings/security", icon: KeyRound },
  { key: "twoFactor", to: "/settings/security#two-factor", icon: ShieldCheck },
  { key: "loginAlerts", to: "/settings/security#login-alerts", icon: Bell },
  { key: "devices", to: "/settings/security#devices", icon: Smartphone },
  { key: "loginActivity", to: "/settings/security#activity", icon: History },
  { key: "notifications", to: "/settings/notifications", icon: Bell },
  { key: "favorites", to: "/settings/content#favorites", icon: ListFilter },
  { key: "muted", to: "/settings/content#mutes", icon: ListFilter },
  { key: "blocking", to: "/settings/content#blocks", icon: Ban },
  { key: "theme", to: "/settings/display#theme", icon: Moon },
  { key: "language", to: "/settings/display#language", icon: Languages },
  { key: "display", to: "/settings/display", icon: Palette },
  { key: "activityLog", to: "/settings/activity-log", icon: History },
];

/** The "Most visited" cards on the settings landing. */
export const MOST_VISITED = ["blocking", "theme", "profilePrivacy", "activityLog"] as const;

export function entryByKey(key: string): SettingsEntry | undefined {
  return SETTINGS_ENTRIES.find((e) => e.key === key);
}

type T = (key: string) => string;

/** Entries whose title, description or keywords contain every word of the query. */
export function searchSettings(query: string, t: T, limit = 8): SettingsEntry[] {
  const words = foldText(query).split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  return SETTINGS_ENTRIES.filter((e) => {
    const base = `polish.settings.entries.${e.key}`;
    const hay = foldText(`${t(`${base}.title`)} ${t(`${base}.desc`)} ${t(`${base}.keywords`)}`);
    return words.every((w) => hay.includes(w));
  }).slice(0, limit);
}
