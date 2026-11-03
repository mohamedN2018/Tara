<script setup lang="ts">
import { Bookmark, Eye, Flag, Info, MapPin, MessageCircle, Scale } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import CompareBar from "@/components/marketplace/CompareBar.vue";
import PriceTag from "@/components/marketplace/PriceTag.vue";
import SellerCard from "@/components/marketplace/SellerCard.vue";
import SellerReviews from "@/components/marketplace/SellerReviews.vue";
import { useCompare } from "@/components/marketplace/useCompare";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { relativeTime } from "@/lib/format";
import { categoryGradient, categoryIcon } from "@/lib/listing";
import { useMediaUrls } from "@/lib/useMediaUrl";
import { type ListingAction, type ListingDetail, marketplaceService } from "@/services/marketplace";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const toasts = useToastStore();
const compare = useCompare();

const listing = ref<ListingDetail | null>(null);
const loading = ref(true);
const error = ref(false);
const saved = ref(false);
const busy = ref(false);
const showReport = ref(false);
const reportReason = ref("");
const showMessage = ref(false);
const message = ref("");

const images = useMediaUrls(() => listing.value?.media?.map((m) => m.media_id) ?? []);
const activeImage = ref(0);

const isOwner = computed(() => !!listing.value?.viewer?.is_owner);
const gradient = computed(() => categoryGradient(listing.value?.category?.slug));
const icon = computed(() => categoryIcon(listing.value?.category?.slug));
const canMessage = computed(
  () => !!listing.value && (listing.value.availability === "available" || listing.value.availability === "reserved"),
);
const inCompare = computed(() => !!listing.value && compare.has(listing.value.id));

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const id = route.params.id as string;
    listing.value = await marketplaceService.get(id);
    saved.value = listing.value.viewer?.is_saved ?? false;
    activeImage.value = 0;
    message.value = t("market.messageDefault");
    // One view per viewer per cooldown, counted server-side; never blocks the page.
    if (!listing.value.viewer?.is_owner) marketplaceService.recordView(id).catch(() => {});
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

async function toggleSave() {
  if (!listing.value) return;
  const next = !saved.value;
  saved.value = next;
  try {
    if (next) await marketplaceService.save(listing.value.id);
    else await marketplaceService.unsave(listing.value.id);
  } catch (e) {
    saved.value = !next;
    toasts.error(e);
  }
}

function toggleCompare() {
  if (listing.value && !compare.toggle(listing.value.id)) toasts.error(t("market.compare.full"));
}

// "Message seller": record the inquiry, then open the DM through chat's API.
async function sendMessage() {
  if (!listing.value || busy.value || !message.value.trim()) return;
  busy.value = true;
  try {
    const link = new URL(router.resolve(`/marketplace/${listing.value.id}`).href, window.location.origin).href;
    const conversationId = await marketplaceService.messageSeller(listing.value, message.value, link);
    // `can_review` stays the server's: a review opens a day after the inquiry.
    if (listing.value.viewer) listing.value.viewer.has_inquired = true;
    showMessage.value = false;
    router.push({ name: "messages", params: { id: conversationId } });
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

async function transition(action: ListingAction) {
  if (!listing.value || busy.value) return;
  busy.value = true;
  try {
    const next = await marketplaceService.transition(listing.value.id, action);
    listing.value = { ...listing.value, ...next };
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

async function submitReport() {
  if (!listing.value || !reportReason.value.trim()) return;
  try {
    await marketplaceService.report(listing.value.id, reportReason.value.trim());
    toasts.success(t("market.reportSent"));
    showReport.value = false;
    reportReason.value = "";
  } catch (e) {
    toasts.error(e); // Keep the text so the report can be resent.
  }
}

function onReviewed() {
  if (listing.value?.viewer) {
    listing.value.viewer.can_review = false;
    listing.value.viewer.has_reviewed = true;
  }
}

onMounted(load);
watch(() => route.params.id, (id, old) => id && id !== old && load());
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[680px]">
      <LoadingSkeleton v-if="loading" :rows="2" />
      <ErrorState v-else-if="error || !listing" @retry="load" />

      <template v-else>
        <div class="card overflow-hidden">
          <!-- Gallery -->
          <div class="relative aspect-video bg-gray-100 dark:bg-gray-800">
            <img
              v-if="images.length"
              :src="images[activeImage]"
              class="h-full w-full object-cover"
              :alt="t('market.imageAlt', { n: activeImage + 1, title: listing.title })"
            />
            <div
              v-else
              class="flex h-full flex-col items-center justify-center gap-2 bg-gradient-to-br text-gray-500 dark:text-gray-300"
              :class="gradient"
            >
              <component :is="icon" class="h-14 w-14 opacity-70" />
              <span v-if="listing.category" class="text-sm font-medium opacity-80">
                {{ listing.category.name }}
              </span>
            </div>
            <span
              v-if="listing.status !== 'active'"
              class="absolute top-3 end-3 rounded-full bg-gray-900/80 px-3 py-1 text-xs font-semibold text-white"
            >
              {{ listing.availability ? t(`market.availability.${listing.availability}`) : t(`market.statuses.${listing.status}`) }}
            </span>
          </div>
          <div v-if="images.length > 1" class="flex gap-2 overflow-x-auto p-2">
            <button
              v-for="(src, i) in images"
              :key="i"
              class="h-14 w-14 shrink-0 overflow-hidden rounded-lg border-2 transition"
              :class="i === activeImage ? 'border-brand-600' : 'border-transparent'"
              :aria-label="t('market.showImage', { n: i + 1 })"
              :aria-pressed="i === activeImage"
              @click="activeImage = i"
            >
              <img :src="src" class="h-full w-full object-cover" alt="" />
            </button>
          </div>

          <div class="p-4">
            <PriceTag :listing="listing" size="lg" />
            <p v-if="isOwner && listing.price_unconfirmed" class="mt-1 text-xs text-amber-700 dark:text-amber-300">
              {{ t("market.priceUnconfirmed") }}
            </p>
            <h1 class="mt-1 text-lg font-semibold" dir="auto">{{ listing.title }}</h1>

            <div class="mt-2 flex flex-wrap items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
              <span class="inline-flex items-center gap-1">
                <MapPin class="h-4 w-4" aria-hidden="true" /> <span dir="auto">{{ listing.location || "—" }}</span>
              </span>
              <span class="rounded-full bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-800">
                {{ t(`market.conditions.${listing.condition}`) }}
              </span>
              <span v-if="listing.category" class="rounded-full bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-800">
                {{ listing.category.name }}
              </span>
              <span class="text-xs">· {{ relativeTime(listing.created_at) }}</span>
              <span v-if="listing.save_count" class="inline-flex items-center gap-1 text-xs">
                · <Bookmark class="h-3 w-3" aria-hidden="true" /> {{ t("market.saves", listing.save_count) }}
              </span>
              <span v-if="isOwner && listing.view_count !== undefined" class="inline-flex items-center gap-1 text-xs">
                · <Eye class="h-3 w-3" aria-hidden="true" /> {{ t("market.views", listing.view_count) }}
              </span>
            </div>

            <p class="mt-4 whitespace-pre-wrap text-sm leading-relaxed" dir="auto">{{ listing.description }}</p>

            <SellerCard :seller-id="listing.seller_id" />

            <!-- Owner actions -->
            <div v-if="isOwner" class="mt-5 space-y-2">
              <p class="text-xs font-medium text-gray-500 dark:text-gray-400">{{ t("market.yourListing") }}</p>
              <div class="flex flex-wrap gap-2">
                <button v-if="listing.status === 'active'" class="btn-ghost" :disabled="busy" @click="transition('reserve')">
                  {{ t("market.reserve") }}
                </button>
                <button v-if="listing.status === 'reserved'" class="btn-ghost" :disabled="busy" @click="transition('reactivate')">
                  {{ t("market.reactivate") }}
                </button>
                <button
                  v-if="listing.status === 'active' || listing.status === 'reserved'"
                  class="btn-primary"
                  :disabled="busy"
                  @click="transition('mark_sold')"
                >
                  {{ t("market.markSold") }}
                </button>
              </div>
            </div>

            <!-- Buyer actions -->
            <div v-else class="mt-5 space-y-3">
              <div class="flex flex-wrap gap-2">
                <button
                  class="btn-primary flex-1"
                  :disabled="busy || !canMessage"
                  :aria-expanded="showMessage"
                  aria-controls="message-seller"
                  @click="showMessage = !showMessage"
                >
                  <MessageCircle class="h-4 w-4" aria-hidden="true" />
                  {{ canMessage ? t("market.contactSeller") : t("market.notAvailable") }}
                </button>
                <button class="btn-ghost" :class="saved ? 'text-brand-600 dark:text-brand-300' : ''" :aria-pressed="saved" @click="toggleSave">
                  <Bookmark class="h-4 w-4" :fill="saved ? 'currentColor' : 'none'" aria-hidden="true" />
                  {{ saved ? t("market.saved") : t("market.save") }}
                </button>
                <button class="btn-ghost" :class="inCompare ? 'text-brand-600 dark:text-brand-300' : ''" :aria-pressed="inCompare" @click="toggleCompare">
                  <Scale class="h-4 w-4" aria-hidden="true" />
                  {{ inCompare ? t("market.compare.remove") : t("market.compare.add") }}
                </button>
              </div>
              <form v-if="showMessage" id="message-seller" class="space-y-2" @submit.prevent="sendMessage">
                <label for="message-body" class="label">{{ t("market.messageLabel") }}</label>
                <textarea id="message-body" v-model="message" class="input min-h-20" dir="auto" rows="3" maxlength="1000" />
                <div class="flex justify-end gap-2">
                  <button type="button" class="btn-ghost" @click="showMessage = false">{{ t("feed.cancel") }}</button>
                  <button type="submit" class="btn-primary" :disabled="busy || !message.trim()">
                    {{ t("market.sendMessage") }}
                  </button>
                </div>
              </form>
            </div>

            <!-- Report -->
            <div v-if="!isOwner" class="mt-3">
              <button
                class="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-red-500 dark:text-gray-400"
                :aria-expanded="showReport"
                @click="showReport = !showReport"
              >
                <Flag class="h-3 w-3" aria-hidden="true" /> {{ t("market.report") }}
              </button>
              <div v-if="showReport" class="mt-2 space-y-2">
                <textarea
                  v-model="reportReason"
                  class="input min-h-16"
                  dir="auto"
                  maxlength="200"
                  :aria-label="t('market.reportReason')"
                  :placeholder="t('market.reportReason')"
                  rows="2"
                />
                <button class="btn-primary" :disabled="!reportReason.trim()" @click="submitReport">
                  {{ t("market.report") }}
                </button>
              </div>
            </div>

            <p
              class="mt-4 flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300"
            >
              <Info class="h-4 w-4 shrink-0" aria-hidden="true" />
              {{ t("market.paymentsNote") }}
            </p>

            <SellerReviews
              :seller-id="listing.seller_id"
              :listing-id="listing.id"
              :can-review="!!listing.viewer?.can_review"
              @reviewed="onReviewed"
            />
          </div>
        </div>
        <div class="h-20" aria-hidden="true" />
      </template>
    </div>
    <CompareBar />
  </AppShell>
</template>
