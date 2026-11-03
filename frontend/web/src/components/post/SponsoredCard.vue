<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { adsService } from "@/services/ads";
import type { SponsoredSlot } from "@/types";

const { ad } = defineProps<{ ad: SponsoredSlot }>();
const { t } = useI18n();
const card = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;

// An ad failing to report must never disturb the feed.
const report = (kind: "impression" | "click") =>
  adsService.event(kind, ad.creative_id, ad.token).catch(() => {});

onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      if (!entries[0]?.isIntersecting) return;
      observer?.disconnect();
      void report("impression");
    },
    { threshold: 0.5 },
  );
  if (card.value) observer.observe(card.value);
});
onBeforeUnmount(() => observer?.disconnect());

function open() {
  void report("click");
  if (ad.link_url) window.open(ad.link_url, "_blank", "noopener,noreferrer");
}
</script>

<template>
  <article ref="card" class="card border-brand-200 p-4 dark:border-brand-900" data-testid="sponsored">
    <span class="text-[10px] font-semibold uppercase tracking-wide text-brand-500">
      {{ t("feed.sponsored") }}
    </span>
    <h3 class="mt-1 text-sm font-bold" dir="auto">{{ ad.headline }}</h3>
    <p v-if="ad.body" class="mt-1 text-sm text-gray-600 dark:text-gray-300" dir="auto">{{ ad.body }}</p>
    <button v-if="ad.cta" class="btn-primary mt-3 w-full" dir="auto" @click="open">{{ ad.cta }}</button>
  </article>
</template>
