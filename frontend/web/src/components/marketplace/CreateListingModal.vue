<script setup lang="ts">
import { X } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import { errorMessage } from "@/lib/errors";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { type CreateListingPayload, marketplaceService } from "@/services/marketplace";
import type { Listing, ListingCategory } from "@/types";

const props = defineProps<{ categories: ListingCategory[] }>();
const emit = defineEmits<{ close: []; created: [listing: Listing] }>();

const { t } = useI18n();
const open = ref(true);
useEscapeKey(open, () => emit("close"));
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);

const CONDITIONS = ["new", "like_new", "good", "fair"];

const form = ref({
  title: "",
  category_id: props.categories[0]?.id ?? "",
  price: "" as string,
  currency: "EGP",
  condition: "good",
  location: "",
  description: "",
});
const submitting = ref(false);
const errorMsg = ref("");

const valid = () =>
  form.value.title.trim().length > 0 &&
  !!form.value.category_id &&
  form.value.price !== "" &&
  Number(form.value.price) >= 0;

async function submit() {
  if (submitting.value || !valid()) return;
  submitting.value = true;
  errorMsg.value = "";
  const payload: CreateListingPayload = {
    category_id: form.value.category_id,
    title: form.value.title.trim(),
    description: form.value.description.trim(),
    price: Number(form.value.price),
    currency: form.value.currency.trim().toUpperCase() || "EGP",
    condition: form.value.condition,
    location: form.value.location.trim(),
    media_ids: [],
  };
  try {
    const created = await marketplaceService.create(payload);
    // New listings start as draft — publish so they go live (auto-approve).
    const live = await marketplaceService.publish(created.id);
    emit("created", live);
  } catch (e) {
    errorMsg.value = errorMessage(e);
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
    >
      <div class="mb-4 flex items-center justify-between">
        <h2 id="listing-dialog-title" class="text-lg font-bold">{{ t("market.createTitle") }}</h2>
        <button class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('market.close')" @click="emit('close')">
          <X class="h-5 w-5" />
        </button>
      </div>

      <form class="space-y-3" @submit.prevent="submit">
        <div>
          <label for="listing-title" class="mb-1 block text-sm font-medium">{{ t("market.titleField") }}</label>
          <input id="listing-title" v-model="form.title" class="input" dir="auto" required maxlength="160" />
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <label for="listing-category" class="mb-1 block text-sm font-medium">{{ t("nav.marketplace") }}</label>
            <select id="listing-category" v-model="form.category_id" class="input">
              <option v-for="c in categories" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
          </div>
          <div>
            <label for="listing-condition" class="mb-1 block text-sm font-medium">{{ t("market.condition") }}</label>
            <select id="listing-condition" v-model="form.condition" class="input">
              <option v-for="c in CONDITIONS" :key="c" :value="c">{{ t(`market.conditions.${c}`) }}</option>
            </select>
          </div>
        </div>

        <div class="grid grid-cols-3 gap-3">
          <div class="col-span-2">
            <label for="listing-price" class="mb-1 block text-sm font-medium">{{ t("market.price") }}</label>
            <input id="listing-price" v-model="form.price" type="number" min="0" step="any" class="input" required />
          </div>
          <div>
            <label for="listing-currency" class="mb-1 block text-sm font-medium">{{ t("market.currency") }}</label>
            <input id="listing-currency" v-model="form.currency" maxlength="3" class="input uppercase" />
          </div>
        </div>

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
          <textarea id="listing-description" v-model="form.description" class="input min-h-24" dir="auto" rows="3" />
        </div>

        <p v-if="errorMsg" class="text-sm text-red-600">{{ errorMsg }}</p>

        <div class="flex justify-end gap-2 pt-1">
          <button type="button" class="btn-ghost" @click="emit('close')">{{ t("feed.cancel") }}</button>
          <button type="submit" class="btn-primary" :disabled="submitting || !valid()">
            {{ submitting ? t("market.publishing") : t("market.publish") }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
