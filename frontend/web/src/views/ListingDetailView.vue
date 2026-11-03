<script setup lang="ts">
import { Bookmark, Flag, Info, MapPin, MessageCircle } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { relativeTime } from "@/lib/format";
import { categoryGradient, categoryIcon, formatPrice } from "@/lib/listing";
import { useMediaUrls } from "@/lib/useMediaUrl";
import { type ListingAction, marketplaceService } from "@/services/marketplace";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";
import type { Listing } from "@/types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const directory = useDirectoryStore();
const toasts = useToastStore();

const listing = ref<Listing | null>(null);
const loading = ref(true);
const error = ref(false);
const saved = ref(false);
const busy = ref(false);
const showReport = ref(false);
const reportReason = ref("");

const images = useMediaUrls(() => listing.value?.media?.map((m) => m.media_id) ?? []);
const activeImage = ref(0);

const isOwner = computed(() => !!listing.value && auth.account?.id === listing.value.seller_id);
const price = computed(() =>
  listing.value ? formatPrice(listing.value.price, listing.value.currency) : "",
);
const gradient = computed(() => categoryGradient(listing.value?.category?.slug));
const icon = computed(() => categoryIcon(listing.value?.category?.slug));

async function load() {
  loading.value = true;
  error.value = false;
  try {
    listing.value = await marketplaceService.get(route.params.id as string);
    activeImage.value = 0;
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

async function contact() {
  if (!listing.value || busy.value) return;
  busy.value = true;
  try {
    await marketplaceService.contact(listing.value.id);
    toasts.success(t("market.contactSent"));
    window.setTimeout(() => router.push("/messages"), 1200);
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
    listing.value = await marketplaceService.transition(listing.value.id, action);
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

onMounted(load);
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
              {{ t(`market.statuses.${listing.status}`) }}
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
            <p class="text-2xl font-bold text-brand-600">{{ price }}</p>
            <h1 class="mt-1 text-lg font-semibold" dir="auto">{{ listing.title }}</h1>

            <div class="mt-2 flex flex-wrap items-center gap-2 text-sm text-gray-500">
              <span class="inline-flex items-center gap-1">
                <MapPin class="h-4 w-4" /> <span dir="auto">{{ listing.location || "—" }}</span>
              </span>
              <span class="rounded-full bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-800">
                {{ t(`market.conditions.${listing.condition}`) }}
              </span>
              <span v-if="listing.category" class="rounded-full bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-800">
                {{ listing.category.name }}
              </span>
              <span class="text-xs text-gray-400">· {{ relativeTime(listing.created_at) }}</span>
              <span v-if="listing.save_count" class="inline-flex items-center gap-1 text-xs text-gray-400">
                · <Bookmark class="h-3 w-3" /> {{ t("market.saves", listing.save_count) }}
              </span>
            </div>

            <p class="mt-4 whitespace-pre-wrap text-sm leading-relaxed" dir="auto">{{ listing.description }}</p>

            <!-- Seller -->
            <RouterLink
              :to="{ name: 'profile-by-id', params: { id: listing.seller_id } }"
              class="mt-4 flex items-center gap-3 rounded-xl border border-gray-100 p-3 transition hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-800/60"
            >
              <UserAvatar :name="directory.label(listing.seller_id)" :media-id="directory.avatarOf(listing.seller_id)" :size="40" />
              <div class="min-w-0">
                <p class="text-xs text-gray-400">{{ t("market.listedBy") }}</p>
                <p class="truncate text-sm font-semibold" dir="auto">{{ directory.label(listing.seller_id) }}</p>
              </div>
              <span class="ms-auto text-xs font-medium text-brand-600">{{ t("market.viewSeller") }}</span>
            </RouterLink>

            <!-- Actions -->
            <div v-if="isOwner" class="mt-5 space-y-2">
              <p class="text-xs font-medium text-gray-400">{{ t("market.yourListing") }}</p>
              <div class="flex flex-wrap gap-2">
                <button
                  v-if="listing.status === 'active'"
                  class="btn-ghost"
                  :disabled="busy"
                  @click="transition('reserve')"
                >
                  {{ t("market.reserve") }}
                </button>
                <button
                  v-if="listing.status === 'reserved'"
                  class="btn-ghost"
                  :disabled="busy"
                  @click="transition('reactivate')"
                >
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

            <div v-else class="mt-5 flex gap-2">
              <button class="btn-primary flex-1" :disabled="busy" @click="contact">
                <MessageCircle class="h-4 w-4" /> {{ t("market.contactSeller") }}
              </button>
              <button class="btn-ghost" :class="saved ? 'text-brand-600' : ''" @click="toggleSave">
                <Bookmark class="h-4 w-4" :fill="saved ? 'currentColor' : 'none'" />
                {{ saved ? t("market.saved") : t("market.save") }}
              </button>
            </div>

            <!-- Report -->
            <div v-if="!isOwner" class="mt-3">
              <button
                class="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-red-500"
                @click="showReport = !showReport"
              >
                <Flag class="h-3 w-3" /> {{ t("market.report") }}
              </button>
              <div v-if="showReport" class="mt-2 space-y-2">
                <textarea
                  v-model="reportReason"
                  class="input min-h-16"
                  dir="auto"
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
              <Info class="h-4 w-4 shrink-0" />
              {{ t("market.paymentsNote") }}
            </p>
          </div>
        </div>
      </template>
    </div>
  </AppShell>
</template>
