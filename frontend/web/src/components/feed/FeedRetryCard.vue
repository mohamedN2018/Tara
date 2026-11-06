<script setup lang="ts">
// The next page could not load after the automatic retries (08 §7.7, WP 4c.4-B3):
// an inline card in the feed, never an English toast.
import { RotateCw, WifiOff } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

defineProps<{ busy?: boolean }>();
const emit = defineEmits<{ retry: [] }>();
const { t } = useI18n();
</script>

<template>
  <section class="card flex items-center gap-3 p-4" role="alert" aria-labelledby="feed-retry-title" data-testid="feed-retry">
    <span class="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-50 text-accent-600 dark:bg-accent-900/40 dark:text-accent-300">
      <WifiOff class="h-5 w-5" aria-hidden="true" />
    </span>
    <div class="min-w-0 flex-1">
      <h2 id="feed-retry-title" class="text-[15px] font-bold text-gray-900 dark:text-white">{{ t("delivery.retry.title") }}</h2>
      <p class="text-sm text-gray-600 dark:text-gray-300">{{ t("delivery.retry.hint") }}</p>
    </div>
    <button type="button" class="btn-primary shrink-0" :disabled="busy" data-testid="feed-retry-button" @click="emit('retry')">
      <!-- A circular arrow reads the same both ways; it is not mirrored. -->
      <RotateCw class="h-4 w-4" :class="busy ? 'animate-spin' : ''" aria-hidden="true" />
      {{ busy ? t("delivery.retry.retrying") : t("delivery.retry.action") }}
    </button>
  </section>
</template>
