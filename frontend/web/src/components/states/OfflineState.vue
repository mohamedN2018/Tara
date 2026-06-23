<script setup lang="ts">
import { WifiOff } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

const { t } = useI18n();
</script>

<template>
  <div
    class="fixed inset-x-0 top-0 z-50 flex items-center justify-center gap-2 bg-amber-500 px-4 py-1.5 text-center text-xs font-medium text-amber-950"
    role="status"
  >
    <WifiOff class="h-4 w-4" />
    {{ t("states.offline") }}
  </div>
</template>
