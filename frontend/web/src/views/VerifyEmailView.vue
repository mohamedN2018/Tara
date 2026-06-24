<script setup lang="ts">
import { CheckCircle2, Loader2, XCircle } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";
import { identityService } from "@/services/identity";

const { t } = useI18n();
const route = useRoute();
const token = computed(() => (route.query.token as string) || "");
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
  <div class="flex min-h-screen items-center justify-center px-4">
    <div class="absolute end-4 top-4 flex gap-2"><LocaleToggle /><ThemeToggle /></div>
    <div class="card w-full max-w-sm p-6 text-center">
      <RouterLink to="/" class="mb-4 block text-2xl font-extrabold text-brand-600">{{ t("app.name") }}</RouterLink>
      <h1 class="mb-4 text-sm text-gray-500">{{ t("auth.verifyTitle") }}</h1>

      <div v-if="state === 'verifying'" class="flex flex-col items-center gap-2 py-4 text-gray-500">
        <Loader2 class="h-8 w-8 animate-spin" />
        <p class="text-sm">{{ t("auth.verifying") }}</p>
      </div>
      <div v-else-if="state === 'ok'" class="flex flex-col items-center gap-2 py-4">
        <CheckCircle2 class="h-10 w-10 text-green-500" />
        <p class="text-sm text-green-700 dark:text-green-300">{{ t("auth.verifySuccess") }}</p>
      </div>
      <div v-else class="flex flex-col items-center gap-2 py-4">
        <XCircle class="h-10 w-10 text-red-500" />
        <p class="text-sm text-red-600">{{ t("auth.verifyFailed") }}</p>
      </div>

      <RouterLink to="/login" class="btn-primary mt-2 w-full">{{ t("auth.loginCta") }}</RouterLink>
    </div>
  </div>
</template>
