<script setup lang="ts">
// End of the feed (08 §7.7, WP 4c.4-B3): shown only when the server says there is
// nothing more (`has_more` false), with ways to keep going.
import { CheckCircle2, ChevronRight, Clapperboard, Search } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

const { t } = useI18n();
</script>

<template>
  <section class="card p-5 text-center" aria-labelledby="feed-end-title" data-testid="feed-end">
    <CheckCircle2 class="mx-auto h-10 w-10 text-brand-600 dark:text-brand-300" aria-hidden="true" />
    <h2 id="feed-end-title" class="mt-2 text-lg font-bold text-gray-900 dark:text-white">{{ t("delivery.end.title") }}</h2>
    <p class="mt-1 text-sm text-gray-600 dark:text-gray-300">{{ t("delivery.end.hint") }}</p>
    <div class="mt-4 flex flex-wrap justify-center gap-2">
      <RouterLink to="/search" class="btn-ghost inline-flex items-center gap-1.5" data-testid="feed-end-explore">
        <Search class="h-4 w-4" aria-hidden="true" />
        {{ t("delivery.end.explore") }}
        <!-- Points along the reading direction: mirrored in RTL. -->
        <ChevronRight class="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" />
      </RouterLink>
      <RouterLink to="/reels" class="btn-ghost inline-flex items-center gap-1.5" data-testid="feed-end-reels">
        <Clapperboard class="h-4 w-4" aria-hidden="true" />
        {{ t("delivery.end.reels") }}
        <ChevronRight class="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" />
      </RouterLink>
    </div>
  </section>
</template>
