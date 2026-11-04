<script setup lang="ts">
// The marketplace's own navigation column: search, the hubs (browse, the
// marketplace's notifications, inbox, buying, selling), "Create new listing"
// and the categories. Desktop: a sticky start column. Phone: a title row, a
// row of pills and the create button. Every entry is a link, so it works from
// any marketplace page (listing, seller shop) and keeps back/forward.
import { Bell, MessageCircle, Plus, Search, ShoppingBag, Store, Tag } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { categoryIcon } from "@/lib/listing";
import type { ListingCategory } from "@/types";

import { MARKET_TABS, type MarketTab } from "./hubs";
import { categoryLabel } from "./useCategories";

// `rail`: the desktop start column; `bar`: the phone/tablet header.
const props = withDefaults(
  defineProps<{
    variant: "rail" | "bar";
    active?: MarketTab | "";
    categories?: ListingCategory[];
    category?: string;
    q?: string;
  }>(),
  { active: "", categories: () => [], category: "", q: "" },
);
const emit = defineEmits<{ create: [] }>();

const { t, te } = useI18n();
const router = useRouter();
const search = ref(props.q);
watch(() => props.q, (v) => (search.value = v));

const ICONS: Record<MarketTab, typeof Store> = {
  browse: Store,
  notifications: Bell,
  inbox: MessageCircle,
  buying: ShoppingBag,
  selling: Tag,
};
const HUBS = MARKET_TABS.map((id) => ({ id, icon: ICONS[id] }));
// Inbox: the marketplace chats themselves, in Messages (folder=marketplace).
const hubLink = (id: MarketTab) =>
  id === "inbox" ? { path: "/messages", query: { folder: "marketplace" } } : { path: "/marketplace", query: id === "browse" ? {} : { tab: id } };
const topCategories = computed(() => props.categories.filter((c) => !c.parent_id));

function submit() {
  const q = search.value.trim();
  router.push({ path: "/marketplace", query: q ? { q } : {} });
}

const row =
  "flex w-full items-center gap-3 rounded-xl px-2 py-2 text-start text-[15px] font-medium transition hover:bg-gray-100 dark:hover:bg-gray-800";
</script>

<template>
  <!-- Desktop: the start column -->
  <aside
    v-if="variant === 'rail'"
    class="card sticky top-20 hidden h-[calc(100vh-6rem)] w-[340px] shrink-0 overflow-y-auto px-3 pb-6 pt-4 lg:block xl:w-[360px]"
    :aria-label="t('commerce.nav.label')"
    data-testid="market-nav"
  >
    <h1 class="px-2 text-2xl font-bold">{{ t("market.title") }}</h1>
    <form class="relative mt-3" role="search" @submit.prevent="submit">
      <Search class="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden="true" />
      <input
        v-model="search"
        type="search"
        class="input rounded-full ps-9"
        dir="auto"
        maxlength="100"
        :placeholder="t('commerce.nav.search')"
        :aria-label="t('commerce.nav.search')"
      />
    </form>

    <nav class="mt-3 space-y-0.5" :aria-label="t('commerce.nav.hubs')">
      <RouterLink
        v-for="h in HUBS"
        :key="h.id"
        :to="hubLink(h.id)"
        :class="[row, active === h.id ? 'bg-brand-50 text-brand-700 dark:bg-brand-950/40 dark:text-brand-200' : '']"
        :aria-current="active === h.id ? 'page' : undefined"
        :data-testid="`market-nav-${h.id}`"
      >
        <span
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
          :class="active === h.id ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200'"
        >
          <component :is="h.icon" class="h-[18px] w-[18px]" aria-hidden="true" />
        </span>
        {{ t(`commerce.nav.${h.id}`) }}
      </RouterLink>
    </nav>

    <button
      type="button"
      class="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-brand-50 py-2 text-sm font-semibold text-brand-700 transition hover:bg-brand-100 dark:bg-brand-950/50 dark:text-brand-200 dark:hover:bg-brand-900/50"
      data-testid="market-create"
      @click="emit('create')"
    >
      <Plus class="h-4 w-4" aria-hidden="true" /> {{ t("commerce.nav.create") }}
    </button>

    <template v-if="topCategories.length">
      <div class="my-4 border-t border-gray-200 dark:border-gray-800" />
      <h2 class="px-2 text-base font-semibold">{{ t("commerce.nav.categories") }}</h2>
      <ul class="mt-1 space-y-0.5">
        <li v-for="c in topCategories" :key="c.id">
          <RouterLink
            :to="{ path: '/marketplace', query: { category: c.slug } }"
            :class="[row, active === 'browse' && category === c.slug ? 'bg-gray-100 dark:bg-gray-800' : '']"
            :aria-current="active === 'browse' && category === c.slug ? 'page' : undefined"
          >
            <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200">
              <component :is="categoryIcon(c.slug)" class="h-[18px] w-[18px]" aria-hidden="true" />
            </span>
            <span class="truncate">{{ categoryLabel(c, t, te) }}</span>
          </RouterLink>
        </li>
      </ul>
    </template>
  </aside>

  <!-- Phone and tablet: a title row and a row of pills -->
  <div v-else class="mb-3 lg:hidden" data-testid="market-nav-mobile">
    <div class="mb-3 flex items-center justify-between gap-2">
      <h1 class="text-xl font-bold">{{ t("market.title") }}</h1>
      <button type="button" class="btn-primary" data-testid="market-create-mobile" @click="emit('create')">
        <Plus class="h-4 w-4" aria-hidden="true" /> {{ t("market.sell") }}
      </button>
    </div>
    <nav class="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1" :aria-label="t('commerce.nav.label')">
      <RouterLink
        v-for="h in HUBS"
        :key="h.id"
        :to="hubLink(h.id)"
        class="chip min-h-9 shrink-0 text-sm"
        :class="{ 'chip-active': active === h.id }"
        :aria-current="active === h.id ? 'page' : undefined"
        :data-testid="`market-pill-${h.id}`"
      >
        <component :is="h.icon" class="h-4 w-4" aria-hidden="true" /> {{ t(`commerce.nav.${h.id}`) }}
      </RouterLink>
    </nav>
  </div>
</template>
