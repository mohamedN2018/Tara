<script setup lang="ts">
// Advanced filters: condition, price type, availability (chips with facet
// counts), price range on the price a buyer pays, currency and location.
// Edits a local draft; "Apply" hands it back so typing does not refetch.
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { ListingFacets } from "@/services/marketplace";

import FilterChip from "./FilterChip.vue";
import {
  AVAILABILITIES,
  type BrowseFilters,
  CONDITIONS,
  emptyFilters,
  toggle,
  toggleAvailability,
} from "./filters";
import { CURRENCIES, PRICE_TYPES } from "./money";

const props = defineProps<{ modelValue: BrowseFilters; facets: ListingFacets | null }>();
const emit = defineEmits<{ "update:modelValue": [value: BrowseFilters] }>();
const { t } = useI18n();

const draft = ref<BrowseFilters>({ ...props.modelValue });
watch(
  () => props.modelValue,
  (v) => (draft.value = { ...v }),
);

function count(dim: "condition" | "price_type" | "availability", value: string): number | null {
  if (!props.facets) return null;
  return props.facets[dim].find((f) => f.value === value)?.count ?? 0;
}

// Chips apply at once (cheap, and the counts update); text inputs wait for Apply.
function flip(dim: "condition" | "price_type" | "availability", value: string) {
  if (dim !== "availability") {
    emit("update:modelValue", { ...props.modelValue, [dim]: toggle(props.modelValue[dim], value) });
    return;
  }
  emit("update:modelValue", {
    ...props.modelValue,
    availability: toggleAvailability(props.modelValue.availability, value),
  });
}

const rangeError = ref(false);
function apply() {
  const lo = draft.value.min_price;
  const hi = draft.value.max_price;
  rangeError.value = !!lo && !!hi && Number(lo) > Number(hi);
  if (rangeError.value) return;
  emit("update:modelValue", {
    ...props.modelValue,
    min_price: lo,
    max_price: hi,
    currency: draft.value.currency,
    location: draft.value.location,
  });
}

function reset() {
  emit("update:modelValue", { ...emptyFilters(), q: props.modelValue.q, sort: props.modelValue.sort });
}
</script>

<template>
  <div class="card mb-4 space-y-4 p-4">
    <fieldset>
      <legend class="label">{{ t("market.condition") }}</legend>
      <div class="flex flex-wrap gap-2">
        <template v-for="c in CONDITIONS" :key="c">
          <FilterChip
            v-if="count('condition', c) !== 0 || modelValue.condition.includes(c)"
            :label="t(`market.conditions.${c}`)"
            :count="count('condition', c)"
            :active="modelValue.condition.includes(c)"
            @toggle="flip('condition', c)"
          />
        </template>
      </div>
    </fieldset>

    <fieldset>
      <legend class="label">{{ t("market.priceType") }}</legend>
      <div class="flex flex-wrap gap-2">
        <template v-for="p in PRICE_TYPES" :key="p">
          <FilterChip
            v-if="count('price_type', p) !== 0 || modelValue.price_type.includes(p)"
            :label="t(`market.priceTypes.${p}`)"
            :count="count('price_type', p)"
            :active="modelValue.price_type.includes(p)"
            @toggle="flip('price_type', p)"
          />
        </template>
      </div>
    </fieldset>

    <fieldset>
      <legend class="label">{{ t("market.availabilityLabel") }}</legend>
      <div class="flex flex-wrap gap-2">
        <FilterChip
          v-for="a in AVAILABILITIES"
          :key="a"
          :label="t(`market.availability.${a}`)"
          :count="count('availability', a)"
          :active="modelValue.availability.length ? modelValue.availability.includes(a) : a === 'available'"
          @toggle="flip('availability', a)"
        />
      </div>
    </fieldset>

    <form class="grid grid-cols-2 gap-3 sm:grid-cols-4" @submit.prevent="apply">
      <div>
        <label for="mf-min" class="label">{{ t("market.filters.minPrice") }}</label>
        <input id="mf-min" v-model="draft.min_price" type="number" min="0" step="any" inputmode="decimal" class="input" dir="ltr" />
      </div>
      <div>
        <label for="mf-max" class="label">{{ t("market.filters.maxPrice") }}</label>
        <input id="mf-max" v-model="draft.max_price" type="number" min="0" step="any" inputmode="decimal" class="input" dir="ltr" />
      </div>
      <div>
        <label for="mf-currency" class="label">{{ t("market.currency") }}</label>
        <select id="mf-currency" v-model="draft.currency" class="input">
          <option value="">{{ t("market.filters.anyCurrency") }}</option>
          <option v-for="c in CURRENCIES" :key="c" :value="c">{{ c }}</option>
        </select>
      </div>
      <div>
        <label for="mf-location" class="label">{{ t("market.location") }}</label>
        <input id="mf-location" v-model="draft.location" class="input" dir="auto" maxlength="160" />
      </div>
      <p v-if="rangeError" class="col-span-full text-sm text-red-600 dark:text-red-400" role="alert">
        {{ t("market.filters.rangeError") }}
      </p>
      <p class="col-span-full text-xs text-gray-500 dark:text-gray-400">{{ t("market.filters.priceHint") }}</p>
      <div class="col-span-full flex justify-end gap-2">
        <button type="button" class="btn-ghost" @click="reset">{{ t("market.filters.reset") }}</button>
        <button type="submit" class="btn-primary">{{ t("market.filters.apply") }}</button>
      </div>
    </form>
  </div>
</template>
