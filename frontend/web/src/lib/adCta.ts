// The ad button text. Creatives store free text, and the default ("Learn more",
// services/ads/ads/models.py) is English, while Arabic advertisers saved the
// Arabic default: both showed as typed whatever the reader's language. A text
// that matches a known call-to-action, in either language and in any case, is
// shown by its key (`adCta.<key>`) in the reader's language; any other text is
// the advertiser's own words and shows as written.

export const CTA_KEYS = ["learn_more", "shop_now", "sign_up", "contact_us", "book_now", "download", "apply_now", "watch_more"] as const;
export type CtaKey = (typeof CTA_KEYS)[number];

const ALIASES: Record<CtaKey, string[]> = {
  learn_more: ["learn more", "اعرف المزيد", "إعرف المزيد", "اعرف أكثر", "معرفة المزيد"],
  shop_now: ["shop now", "تسوق الآن", "تسوّق الآن", "تسوق الان"],
  sign_up: ["sign up", "سجل الآن", "سجّل الآن", "سجل الان", "اشترك الآن"],
  contact_us: ["contact us", "تواصل معنا", "اتصل بنا"],
  book_now: ["book now", "احجز الآن", "احجز الان"],
  download: ["download", "تنزيل", "حمّل", "حمل"],
  apply_now: ["apply now", "قدّم الآن", "قدم الآن", "قدم الان"],
  watch_more: ["watch more", "شاهد المزيد"],
};

const normalise = (text: string) => text.normalize("NFC").trim().replace(/\s+/g, " ").toLowerCase();

const BY_TEXT = new Map<string, CtaKey>();
for (const key of CTA_KEYS) {
  BY_TEXT.set(key.replace("_", " "), key);
  BY_TEXT.set(key, key);
  for (const alias of ALIASES[key]) BY_TEXT.set(normalise(alias), key);
}

/** The known call-to-action a button text stands for; null for the advertiser's own words. */
export function ctaKey(text: string | null | undefined): CtaKey | null {
  if (!text) return null;
  return BY_TEXT.get(normalise(text)) ?? null;
}

/** The button text to show: a known call-to-action in the reader's language, else as written. */
export function ctaLabel(text: string | null | undefined, t: (key: string) => string): string {
  const key = ctaKey(text);
  return key ? t(`adCta.${key}`) : (text ?? "");
}
