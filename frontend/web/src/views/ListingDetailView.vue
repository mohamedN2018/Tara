<script setup lang="ts">
import { Bookmark, Info, MapPin, MessageCircle } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { useMediaUrl } from "@/lib/useMediaUrl";
import { marketplaceService } from "@/services/marketplace";
import type { Listing } from "@/types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();

const listing = ref<(Listing & { cover_media_id?: string | null; media_ids?: string[] }) | null>(
  null,
);
const loading = ref(true);
const error = ref(false);
const saved = ref(false);
const cover = useMediaUrl(() => listing.value?.cover_media_id);

async function load() {
  loading.value = true;
  error.value = false;
  try {
    listing.value = await marketplaceService.get(route.params.id as string);
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
  } catch {
    saved.value = !next;
  }
}

async function contact() {
  if (!listing.value) return;
  // Triggers marketplace.contact.requested; chat opens the conversation async.
  await marketplaceService.contact(listing.value.id);
  router.push("/messages");
}

onMounted(load);
</script>

<template>
  <AppShell>
    <LoadingSkeleton v-if="loading" :rows="2" />
    <ErrorState v-else-if="error || !listing" @retry="load" />

    <template v-else>
      <div class="card overflow-hidden">
        <div class="aspect-video bg-gray-100 dark:bg-gray-800">
          <img
            v-if="cover"
            :src="cover"
            class="h-full w-full object-cover"
            alt=""
          />
        </div>
        <div class="p-4">
          <p class="text-2xl font-bold text-brand-600">{{ listing.price }} {{ listing.currency }}</p>
          <h1 class="mt-1 text-lg font-semibold">{{ listing.title }}</h1>
          <p class="mt-1 flex items-center gap-2 text-sm text-gray-500">
            <MapPin class="h-4 w-4" /> {{ listing.location || "—" }}
            <span class="rounded bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-800">
              {{ listing.condition }}
            </span>
          </p>
          <p class="mt-4 whitespace-pre-wrap text-sm leading-relaxed">{{ listing.description }}</p>

          <div class="mt-5 flex gap-2">
            <button class="btn-primary flex-1" @click="contact">
              <MessageCircle class="h-4 w-4" /> {{ t("market.contactSeller") }}
            </button>
            <button class="btn-ghost" :class="saved ? 'text-brand-600' : ''" @click="toggleSave">
              <Bookmark class="h-4 w-4" :fill="saved ? 'currentColor' : 'none'" />
              {{ saved ? t("market.saved") : t("market.save") }}
            </button>
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
  </AppShell>
</template>
