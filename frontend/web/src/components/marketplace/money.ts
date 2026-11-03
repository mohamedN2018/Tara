// Listing money: three price states and per-currency minor units.
// QTech's formatter rounded 3-decimal currencies to 2 (12.125 KWD -> 12.13);
// this one keeps each currency's real minor units (ISO 4217).
import type { Listing } from "@/types";

export const CURRENCY_MINOR_UNITS: Record<string, number> = {
  EGP: 2,
  USD: 2,
  EUR: 2,
  GBP: 2,
  SAR: 2,
  AED: 2,
  QAR: 2,
  KWD: 3,
  BHD: 3,
  OMR: 3,
  JOD: 3,
  IQD: 3,
  LYD: 3,
  TND: 3,
  MAD: 2,
  DZD: 2,
  LBP: 2,
  SDG: 2,
  TRY: 2,
};
export const CURRENCIES = Object.keys(CURRENCY_MINOR_UNITS);
export const PRICE_TYPES = ["fixed", "negotiable", "free"] as const;
export type PriceType = (typeof PRICE_TYPES)[number];

export function minorUnits(currency: string): number {
  return CURRENCY_MINOR_UNITS[currency?.toUpperCase()] ?? 2;
}

/** "12.1250" KWD -> "KWD 12.125"; whole amounts drop the decimals ("EGP 1,500"). */
export function formatMoney(amount: string | number, currency: string, locale?: string): string {
  const n = Number(amount);
  const code = (currency || "").toUpperCase();
  if (!Number.isFinite(n)) return `${amount} ${code}`.trim();
  const digits = minorUnits(code);
  const opts: Intl.NumberFormatOptions = {
    minimumFractionDigits: Number.isInteger(n) ? 0 : digits,
    maximumFractionDigits: digits,
  };
  try {
    return new Intl.NumberFormat(locale, { ...opts, style: "currency", currency: code }).format(n);
  } catch {
    // Unknown code for this runtime: number plus the code, still with the right digits.
    return `${new Intl.NumberFormat(locale, opts).format(n)} ${code}`;
  }
}

export type PriceView =
  | { kind: "free" }
  | { kind: "offer" } // negotiable, no price
  | { kind: "price"; amount: string; was: string | null; negotiable: boolean };

/** What a price tag shows, without deciding on wording (that is i18n's job). */
export function priceView(
  listing: Pick<Listing, "price" | "price_type" | "sale_price" | "currency">,
  locale?: string,
): PriceView {
  const type = listing.price_type ?? (Number(listing.price) === 0 ? "free" : "fixed");
  if (type === "free") return { kind: "free" };
  if (listing.price === null || listing.price === undefined || listing.price === "") {
    return { kind: "offer" };
  }
  const onSale = listing.sale_price !== null && listing.sale_price !== undefined;
  return {
    kind: "price",
    amount: formatMoney(onSale ? listing.sale_price! : listing.price, listing.currency, locale),
    was: onSale ? formatMoney(listing.price, listing.currency, locale) : null,
    negotiable: type === "negotiable",
  };
}

/** Client-side mirror of the server rules, for inline form errors (server is final). */
export function pricingError(input: {
  price_type: PriceType;
  price: string;
  sale_price: string;
  currency: string;
}): string | null {
  const has = (v: string) => v.trim() !== "";
  const places = (v: string) => (v.includes(".") ? v.split(".")[1].replace(/0+$/, "").length : 0);
  const price = Number(input.price);
  const sale = Number(input.sale_price);
  if (!CURRENCIES.includes(input.currency)) return "currency";
  if (input.price_type === "free") return has(input.sale_price) ? "sale_price_not_allowed" : null;
  if (has(input.price) && (!Number.isFinite(price) || price < 0)) return "price_invalid";
  if (input.price_type === "fixed" && (!has(input.price) || price <= 0)) return "price_required";
  if (input.price_type === "negotiable" && has(input.price) && price <= 0) return "price_required";
  if (has(input.price) && places(input.price) > minorUnits(input.currency)) return "too_many_decimals";
  if (has(input.sale_price)) {
    if (!has(input.price)) return "sale_without_price";
    if (!Number.isFinite(sale) || sale < 0 || sale >= price) return "sale_not_below_price";
    if (places(input.sale_price) > minorUnits(input.currency)) return "too_many_decimals";
  }
  return null;
}
