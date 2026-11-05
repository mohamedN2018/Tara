// A Page's category is free text (up to 80 characters), so the server stores
// whatever the owner typed: often a common English category ("Science",
// "News & Media"). Those show in the reader's language through a slug map
// (i18n `polish.pageCategories.<slug>`); anything else shows as typed.

/** "News & Media" -> "news_and_media"; "Science & Technology" -> "science_and_technology". */
export function categorySlug(category: string): string {
  return category
    .normalize("NFKD")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

type Translate = { t: (key: string) => string; te: (key: string) => boolean };

/** The category in the reader's language when it is a known one, else as typed. */
export function pageCategoryLabel(category: string | null | undefined, i18n: Translate): string {
  const raw = (category ?? "").trim();
  if (!raw) return "";
  const slug = categorySlug(raw);
  const key = `polish.pageCategories.${slug}`;
  return slug && i18n.te(key) ? i18n.t(key) : raw;
}
