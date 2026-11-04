// The settings & privacy centre's sections (/settings/:section), grouped the way
// the left navigation shows them. Every entry is backed by a real endpoint.
import { Bell, KeyRound, ListFilter, Lock, type LucideIcon, Palette, UserRound } from "lucide-vue-next";

export const SETTINGS_SECTIONS = ["account", "privacy", "security", "notifications", "content", "display"] as const;
export type SettingsSection = (typeof SETTINGS_SECTIONS)[number];

export interface SettingsNavItem {
  id: SettingsSection;
  icon: LucideIcon;
}

export interface SettingsNavGroup {
  id: "preferences" | "audience" | "security" | "information";
  items: SettingsNavItem[];
}

export const SETTINGS_GROUPS: SettingsNavGroup[] = [
  {
    id: "preferences",
    items: [
      { id: "notifications", icon: Bell },
      { id: "content", icon: ListFilter },
      { id: "display", icon: Palette },
    ],
  },
  { id: "audience", items: [{ id: "privacy", icon: Lock }] },
  { id: "security", items: [{ id: "security", icon: KeyRound }] },
  { id: "information", items: [{ id: "account", icon: UserRound }] },
];

export const SECTION_ICON: Record<SettingsSection, LucideIcon> = {
  account: UserRound,
  privacy: Lock,
  security: KeyRound,
  notifications: Bell,
  content: ListFilter,
  display: Palette,
};

export function isSettingsSection(value: unknown): value is SettingsSection {
  return typeof value === "string" && (SETTINGS_SECTIONS as readonly string[]).includes(value);
}

/**
 * Old one-page anchors (/settings#notifications, #tags, ...) and the anchors
 * other screens link to: the section that now holds each one.
 */
export const LEGACY_HASH: Record<string, { section: SettingsSection; hash?: string }> = {
  account: { section: "account" },
  notifications: { section: "notifications" },
  privacy: { section: "privacy" },
  relationships: { section: "privacy", hash: "#relationships" },
  tags: { section: "privacy", hash: "#tags" },
  security: { section: "security" },
  sessions: { section: "security", hash: "#devices" },
  content: { section: "content" },
  favorites: { section: "content", hash: "#favorites" },
  muted: { section: "content", hash: "#mutes" },
  blocked: { section: "content", hash: "#blocks" },
  display: { section: "display" },
};
