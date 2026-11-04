<script setup lang="ts">
// Create a listing, or edit one of the seller's own (`listing` given). A new
// listing is created as a draft, then published unless "Save as draft" is used;
// an edited draft or rejected listing can be saved and (re)submitted in one go.
import { X } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { apiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import {
  type CreateListingPayload,
  LISTING_MEDIA_ERRORS,
  type ListingDetail,
  marketplaceService,
  MAX_LISTING_PHOTOS,
} from "@/services/marketplace";
import type { Listing, ListingCategory } from "@/types";

import ListingPhotos from "./ListingPhotos.vue";
import { CURRENCIES, PRICE_TYPES, type PriceType, pricingError } from "./money";
import { categoryLabel } from "./useCategories";

const props = defineProps<{ categories: ListingCategory[]; listing?: ListingDetail | null }>();
const emit = defineEmits<{ close: []; created: [listing: Listing]; saved: [listing: ListingDetail] }>();

const { t, te } = useI18n();
const open = ref(true);
useEscapeKey(open, () => emit("close"));
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);

const CONDITIONS = ["new", "like_new", "good", "fair"];
const editing = computed(() => !!props.listing);
// A draft or a rejected listing goes (back) to buyers once saved and published.
const canPublish = computed(() => !props.listing || ["draft", "rejected"].includes(props.listing.status));

const start = props.listing;
const form = ref({
  title: start?.title ?? "",
  category_id: start?.category?.id ?? props.categories[0]?.id ?? "",
  price_type: (start?.price_type ?? "fixed") as PriceType,
  price: start?.price != null && start.price_type !== "free" ? String(start.price) : "",
  sale_price: start?.sale_price != null ? String(start.sale_price) : "",
  currency: start?.currency ?? "EGP",
  condition: start?.condition ?? "good",
  location: start?.location ?? "",
  description: start?.description ?? "",
});
const photos = ref<string[]>(start?.media?.map((m) => m.media_id) ?? []);
const uploading = ref(false);
const submitting = ref(false);
const errorMsg = ref("");

// The category list, plus a listing's own category when it is not a top choice.
const categoryOptions = computed(() => {
  const list = [...props.categories];
  if (start?.category && !list.some((c) => c.id === start.category?.id)) list.unshift(start.category);
  return list;
});

const priceProblem = computed(() =>
  pricingError({
    price_type: form.value.price_type,
    price: String(form.value.price ?? ""),
    sale_price: String(form.value.sale_price ?? ""),
    currency: form.value.currency,
  }),
);
const valid = () =>
  form.value.title.trim().length > 0 && !!form.value.category_id && !priceProblem.value && !uploading.value;
const amountOrNull = (v: string | number) => (String(v ?? "").trim() === "" ? null : String(v));

function failure(e: unknown): string {
  const { details = [] } = apiError(e);
  const code = details.map((d) => d.code).find((c) => !!c && c in LISTING_MEDIA_ERRORS);
  return code ? t(LISTING_MEDIA_ERRORS[code], { max: MAX_LISTING_PHOTOS }) : errorMessage(e);
}

async function submit(publish = true) {
  if (submitting.value || !valid()) return;
  submitting.value = true;
  errorMsg.value = "";
  const payload: CreateListingPayload = {
    category_id: form.value.category_id,
    title: form.value.title.trim(),
    description: form.value.description.trim(),
    price_type: form.value.price_type,
    price: form.value.price_type === "free" ? null : amountOrNull(form.value.price),
    sale_price: form.value.price_type === "free" ? null : amountOrNull(form.value.sale_price),
    currency: form.value.currency,
    condition: form.value.condition,
    location: form.value.location.trim(),
    media_ids: photos.value,
  };
  try {
    if (props.listing) {
      // The category is fixed once listed; everything else, photos included, can change.
      const { category_id: _fixed, ...changes } = payload;
      void _fixed;
      let saved = await marketplaceService.update(props.listing.id, changes);
      if (publish && canPublish.value) {
        saved = { ...saved, ...(await marketplaceService.publish(props.listing.id)) };
      }
      emit("saved", saved);
      return;
    }
    const created = await marketplaceService.create(payload);
    // New listings start as draft; publishing makes them live (or sends them to review).
    emit("created", publish ? await marketplaceService.publish(created.id) : created);
  } catch (e) {
    errorMsg.value = failure(e);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 backdrop-blur-sm p-0 sm:items-center sm:p-4">
    <div class="fixed inset-0" @click="emit('close')" />
    <div
      ref="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="listing-dialog-title"
      tabindex="-1"
      class="card relative z-10 animate-pop-in shadow-pop max-h-[92vh] w-full overflow-y-auto rounded-b-none rounded-t-2xl p-4 sm:max-w-lg sm:rounded-2xl sm:p-5"
      data-testid="listing-dialog"
    >
      <div class="mb-4 flex items-center justify-between">
        <h2 id="listing-dialog-title" class="text-lg font-bold">
          {{ editing ? t("commerce.listing.editTitle") : t("market.createTitle") }}
        </h2>
        <button class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('market.close')" @click="emit('close')">
          <X class="h-5 w-5" />
        </button>
      </div>

      <form class="space-y-3" @submit.prevent="submit(true)">
        <ListingPhotos v-model="photos" :disabled="submitting" @update:busy="uploading = $event" />

        <div>
          <label for="listing-title" class="mb-1 block text-sm font-medium">{{ t("market.titleField") }}</label>
          <input id="listing-title" v-model="form.title" class="input" dir="auto" required maxlength="160" />
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label for="listing-category" class="mb-1 block text-sm font-medium">{{ t("market.category") }}</label>
            <select id="listing-category" v-model="form.category_id" class="input" :disabled="editing">
              <option v-for="c in categoryOptions" :key="c.id" :value="c.id">{{ categoryLabel(c, t, te) }}</option>
            </select>
          </div>
          <div>
            <label for="listing-condition" class="mb-1 block text-sm font-medium">{{ t("market.condition") }}</label>
            <select id="listing-condition" v-model="form.condition" class="input">
              <option v-for="c in CONDITIONS" :key="c" :value="c">{{ t(`market.conditions.${c}`) }}</option>
            </select>
          </div>
        </div>

        <fieldset>
          <legend class="mb-1 block text-sm font-medium">{{ t("market.priceType") }}</legend>
          <div class="flex gap-1 rounded-xl bg-gray-100 p-1 text-sm dark:bg-gray-800">
            <label
              v-for="p in PRICE_TYPES"
              :key="p"
              class="flex-1 cursor-pointer rounded-lg py-1.5 text-center font-medium transition has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-400"
              :class="form.price_type === p ? 'bg-white text-brand-600 shadow-sm dark:bg-gray-900 dark:text-brand-300' : 'text-gray-600 dark:text-gray-300'"
            >
              <input v-model="form.price_type" type="radio" name="price-type" :value="p" class="sr-only" />
              {{ t(`market.priceTypes.${p}`) }}
            </label>
          </div>
        </fieldset>

        <div v-if="form.price_type !== 'free'" class="grid grid-cols-3 gap-3">
          <div>
            <label for="listing-price" class="mb-1 block text-sm font-medium">
              {{ t("market.price") }}
              <span v-if="form.price_type === 'negotiable'" class="text-xs text-gray-500 dark:text-gray-400">({{ t("market.optional") }})</span>
            </label>
            <input id="listing-price" v-model="form.price" type="number" min="0" step="any" inputmode="decimal" dir="ltr" class="input" :required="form.price_type === 'fixed'" />
          </div>
          <div>
            <label for="listing-sale" class="mb-1 block text-sm font-medium">
              {{ t("market.salePrice") }} <span class="text-xs text-gray-500 dark:text-gray-400">({{ t("market.optional") }})</span>
            </label>
            <input id="listing-sale" v-model="form.sale_price" type="number" min="0" step="any" inputmode="decimal" dir="ltr" class="input" />
          </div>
          <div>
            <label for="listing-currency" class="mb-1 block text-sm font-medium">{{ t("market.currency") }}</label>
            <select id="listing-currency" v-model="form.currency" class="input">
              <option v-for="c in CURRENCIES" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>
        </div>
        <p v-if="priceProblem && (form.price !== '' || form.sale_price !== '')" class="text-xs text-red-600 dark:text-red-400" role="alert">
          {{ t(`market.priceErrors.${priceProblem}`) }}
        </p>
        <p v-else-if="form.price_type === 'negotiable' && form.price === ''" class="text-xs text-gray-500 dark:text-gray-400">
          {{ t("market.offerHint") }}
        </p>

        <div>
          <label for="listing-location" class="mb-1 block text-sm font-medium">
            {{ t("market.location") }} <span class="text-xs text-gray-500 dark:text-gray-400">({{ t("market.optional") }})</span>
          </label>
          <input id="listing-location" v-model="form.location" class="input" dir="auto" maxlength="160" />
        </div>

        <div>
          <label for="listing-description" class="mb-1 block text-sm font-medium">
            {{ t("market.description") }} <span class="text-xs text-gray-500 dark:text-gray-400">({{ t("market.optional") }})</span>
          </label>
          <textarea id="listing-description" v-model="form.description" class="input min-h-24" dir="auto" rows="3" maxlength="5000" />
        </div>

        <p v-if="errorMsg" class="text-sm text-red-600 dark:text-red-400" role="alert">{{ errorMsg }}</p>

        <div class="flex flex-wrap justify-end gap-2 pt-1">
          <button type="button" class="btn-ghost" @click="emit('close')">{{ t("feed.cancel") }}</button>
          <button
            v-if="!editing || canPublish"
            type="button"
            class="btn-ghost"
            data-testid="listing-save-only"
            :disabled="submitting || !valid()"
            @click="submit(false)"
          >
            {{ editing ? t("commerce.listing.saveChanges") : t("commerce.listing.saveDraft") }}
          </button>
          <button type="submit" class="btn-primary" data-testid="listing-submit" :disabled="submitting || !valid()">
            <template v-if="submitting">{{ t("market.publishing") }}</template>
            <template v-else-if="!editing">{{ t("market.publish") }}</template>
            <template v-else-if="canPublish">
              {{ listing?.status === "rejected" ? t("commerce.listing.saveResubmit") : t("commerce.listing.savePublish") }}
            </template>
            <template v-else>{{ t("commerce.listing.saveChanges") }}</template>
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
