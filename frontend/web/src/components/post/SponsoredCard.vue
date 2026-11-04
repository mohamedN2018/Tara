<script setup lang="ts">
import { Undo2, X } from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { hiddenAds, hideAd, unhideAd } from "@/lib/hiddenAds";
import { adsService } from "@/services/ads";
import type { SponsoredSlot } from "@/types";

const { ad } = defineProps<{ ad: SponsoredSlot }>();
const { t } = useI18n();
const card = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;
let seen = false;

// Hidden for this session only: the ads service has no "hide ad" endpoint yet.
const hidden = computed(() => hiddenAds.value.has(ad.creative_id));

// An ad failing to report must never disturb the feed.
const report = (kind: "impression" | "click") =>
  adsService.event(kind, ad.creative_id, ad.token).catch(() => {});

function watchImpression() {
  observer?.disconnect();
  if (seen || hidden.value || !card.value) return;
  observer = new IntersectionObserver(
    (entries) => {
      if (!entries[0]?.isIntersecting) return;
      observer?.disconnect();
      seen = true;
      void report("impression");
    },
    { threshold: 0.5 },
  );
  observer.observe(card.value);
}

onMounted(watchImpression);
// The card element is replaced while hidden; watch the new one after an undo.
watch(card, watchImpression, { flush: "post" });
onBeforeUnmount(() => observer?.disconnect());

function open() {
  void report("click");
  if (ad.link_url) window.open(ad.link_url, "_blank", "noopener,noreferrer");
}
</script>

<template>
  <div
    v-if="hidden"
    class="card flex items-center gap-3 p-4 text-sm"
    role="status"
    data-testid="sponsored-hidden"
  >
    <p class="min-w-0 flex-1">
      <span class="block font-semibold">{{ t("homeFeed.ad.hidden") }}</span>
      <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t("homeFeed.ad.hiddenHint") }}</span>
    </p>
    <button type="button" class="btn-ghost shrink-0" @click="unhideAd(ad.creative_id)">
      <Undo2 class="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" /> {{ t("homeFeed.undo") }}
    </button>
  </div>
  <article v-else ref="card" class="card border-brand-200 p-4 dark:border-brand-900" data-testid="sponsored">
    <div class="flex items-start justify-between gap-2">
      <span class="text-[10px] font-semibold uppercase tracking-wide text-brand-700 dark:text-brand-300">
        {{ t("feed.sponsored") }}
      </span>
      <button
        type="button"
        class="-m-1.5 rounded-full p-1.5 text-gray-500 transition hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-800"
        :aria-label="t('homeFeed.ad.hide')"
        :title="t('homeFeed.ad.hide')"
        @click="hideAd(ad.creative_id)"
      >
        <X class="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
    <h3 class="mt-1 text-sm font-bold" dir="auto">{{ ad.headline }}</h3>
    <p v-if="ad.body" class="mt-1 text-sm text-gray-600 dark:text-gray-300" dir="auto">{{ ad.body }}</p>
    <button v-if="ad.cta" class="btn-primary mt-3 w-full" dir="auto" @click="open">{{ ad.cta }}</button>
  </article>
</template>
