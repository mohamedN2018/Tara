<script setup lang="ts">
// The "new posts" pill (Tara Intelligence 06 §6.1, 08 §7.6). The number is the
// server's `peek` `new_count`, never a client count; when the server capped it the
// pill says "N or more" in words (no "+N", which reads backwards in RTL).
import { ArrowUp } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{ count: number; capped?: boolean }>();
const emit = defineEmits<{ reveal: [] }>();
const { t } = useI18n();

const label = computed(() =>
  props.capped ? t("homeRefresh.pillCapped", { count: props.count }) : t("homeRefresh.pill", { count: props.count }, props.count),
);
</script>

<template>
  <!-- Zero height, no margin: showing the pill never moves the cards under it. -->
  <div class="sticky top-16 z-10 !mt-0 flex h-0 items-start justify-center overflow-visible" data-testid="new-posts-pill">
    <button
      type="button"
      class="mt-2 inline-flex items-center gap-1.5 rounded-full bg-brand-600 px-4 py-1.5 text-sm font-medium text-white shadow-lg transition hover:bg-brand-700"
      :data-count="count"
      :data-capped="capped ? 'true' : 'false'"
      @click="emit('reveal')"
    >
      <ArrowUp class="h-4 w-4" aria-hidden="true" />
      <span dir="auto">{{ label }}</span>
    </button>
  </div>
</template>
