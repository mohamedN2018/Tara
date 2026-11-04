// The marketplace hubs, in navigation order. `?tab=` carries one; the older
// `mine` and `saved` tabs still open their new homes (Selling, Buying).
export const MARKET_TABS = ["browse", "notifications", "inbox", "buying", "selling"] as const;
export type MarketTab = (typeof MARKET_TABS)[number];

const ALIASES: Record<string, MarketTab> = { mine: "selling", saved: "buying" };

export function tabFromQuery(value: unknown): MarketTab {
  const v = typeof value === "string" ? value : "";
  if ((MARKET_TABS as readonly string[]).includes(v)) return v as MarketTab;
  return ALIASES[v] ?? "browse";
}
