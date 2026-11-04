import { ref } from "vue";

import { marketplaceService } from "@/services/marketplace";
import type { ListingCategory } from "@/types";

// One categories request per page load, shared by the navigation column and the views.
let pending: Promise<ListingCategory[]> | null = null;
const categories = ref<ListingCategory[]>([]);

export function useCategories() {
  if (!pending) {
    pending = marketplaceService.categories().then(
      (list) => (categories.value = list),
      (e) => {
        pending = null; // try again next time
        throw e;
      },
    );
  }
  return { categories, ready: pending };
}

/** Tests only. */
export function resetCategories() {
  pending = null;
  categories.value = [];
}

/**
 * The category's name in the UI language: the seeded slugs have translations
 * under `commerce.categoryNames`; anything else shows the server's name.
 */
export function categoryLabel(
  category: Pick<ListingCategory, "slug" | "name"> | null | undefined,
  t: (key: string) => string,
  te: (key: string) => boolean,
): string {
  if (!category) return "";
  const key = `commerce.categoryNames.${(category.slug || "").replace(/-/g, "_")}`;
  return category.slug && te(key) ? t(key) : category.name;
}
