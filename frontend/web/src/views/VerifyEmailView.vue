<script setup lang="ts">
import { CheckCircle2, Loader2, XCircle } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import AuthLayout from "@/components/brand/AuthLayout.vue";
import { identityService } from "@/services/identity";

const { t } = useI18n();
const route = useRoute();
const token = computed(() => (typeof route.query.token === "string" ? route.query.token : ""));
const state = ref<"verifying" | "ok" | "fail">("verifying");

onMounted(async () => {
  if (!token.value) {
    state.value = "fail";
    return;
  }
  try {
    await identityService.verifyEmail(token.value);
    state.value = "ok";
  } catch {
    state.value = "fail";
  }
});
</script>

<template>
  <AuthLayout :title="t('auth.verifyTitle')" centered>

      <div v-if="state === 'verifying'" class="flex flex-col items-center gap-2 py-4 text-gray-500 dark:text-gray-400">
        <Loader2 class="h-8 w-8 animate-spin" />
        <p class="text-sm" role="status">{{ t("auth.verifying") }}</p>
      </div>
      <div v-else-if="state === 'ok'" class="flex flex-col items-center gap-2 py-4">
        <CheckCircle2 class="h-10 w-10 text-green-500" />
        <p class="text-sm text-green-700 dark:text-green-300" role="status">{{ t("auth.verifySuccess") }}</p>
      </div>
      <div v-else class="flex flex-col items-center gap-2 py-4">
        <XCircle class="h-10 w-10 text-red-500" />
        <p class="text-sm text-red-600" role="alert">{{ t("auth.verifyFailed") }}</p>
      </div>

      <RouterLink to="/login" class="btn-gradient mt-2 w-full py-3 text-base">{{ t("auth.loginCta") }}</RouterLink>
  </AuthLayout>
</template>
