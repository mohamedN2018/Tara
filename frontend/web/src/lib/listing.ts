// Presentation helpers for marketplace listings (no backend coupling).
import { Building2, Car, Laptop, Package, Shirt, Sofa, Sprout, Wrench } from "lucide-vue-next";

const ICONS: Record<string, typeof Package> = {
  electronics: Laptop,
  vehicles: Car,
  furniture: Sofa,
  fashion: Shirt,
  "home-garden": Sprout,
  property: Building2,
  services: Wrench,
  other: Package,
};

export function categoryIcon(slug?: string | null): typeof Package {
  return ICONS[slug ?? ""] ?? Package;
}


// Category → soft gradient used for the image placeholder when a listing has
// no uploaded media (keeps the grid attractive without faking a photo).
const GRADIENTS: Record<string, string> = {
  electronics: "from-sky-100 to-indigo-100 dark:from-sky-900/40 dark:to-indigo-900/30",
  vehicles: "from-orange-100 to-amber-100 dark:from-orange-900/40 dark:to-amber-900/30",
  furniture: "from-amber-100 to-yellow-100 dark:from-amber-900/40 dark:to-yellow-900/30",
  fashion: "from-pink-100 to-rose-100 dark:from-pink-900/40 dark:to-rose-900/30",
  "home-garden": "from-green-100 to-emerald-100 dark:from-green-900/40 dark:to-emerald-900/30",
  property: "from-teal-100 to-cyan-100 dark:from-teal-900/40 dark:to-cyan-900/30",
  services: "from-violet-100 to-purple-100 dark:from-violet-900/40 dark:to-purple-900/30",
  other: "from-gray-100 to-gray-200 dark:from-gray-800 dark:to-gray-700",
};

export function categoryGradient(slug?: string | null): string {
  return GRADIENTS[slug ?? ""] ?? GRADIENTS.other;
}

export function formatPrice(price: string | number, currency: string): string {
  const n = Number(price);
  if (Number.isNaN(n)) return `${price} ${currency}`;
  return `${n.toLocaleString()} ${currency}`;
}
