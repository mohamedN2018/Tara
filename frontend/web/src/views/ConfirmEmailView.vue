<script setup lang="ts">
// Opened from the link sent to a NEW email address: confirms the change.
import { CheckCircle2, Loader2, XCircle } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import AuthLayout from "@/components/brand/AuthLayout.vue";
import { apiError } from "@/lib/api";
import { identityService } from "@/services/identity";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();
const route = useRoute();
const auth = useAuthStore();
const state = ref<"working" | "ok" | "fail" | "in_use">("working");

onMounted(async () => {
  const token = typeof route.query.token === "string" ? route.query.token : "";
  if (!token) {
    state.value = "fail";
    return;
  }
  try {
    const account = await identityService.confirmEmailChange(token);
    // Same account signed in here: show the new address right away.
    if (auth.account && auth.account.id === account.id) auth.account = account;
    state.value = "ok";
  } catch (e) {
    state.value = apiError(e).code === "conflict" ? "in_use" : "fail";
  }
});
</script>

<template>
  <AuthLayout :title="t('accountSecurity.confirm.title')" centered>
    <div v-if="state === 'working'" class="flex flex-col items-center gap-2 py-4 text-gray-500 dark:text-gray-400">
      <Loader2 class="h-8 w-8 animate-spin" aria-hidden="true" />
      <p class="text-sm" role="status">{{ t("accountSecurity.confirm.working") }}</p>
    </div>
    <div v-else-if="state === 'ok'" class="flex flex-col items-center gap-2 py-4">
      <CheckCircle2 class="h-10 w-10 text-green-500" aria-hidden="true" />
      <p class="text-sm text-green-700 dark:text-green-300" role="status">{{ t("accountSecurity.confirm.success") }}</p>
    </div>
    <div v-else class="flex flex-col items-center gap-2 py-4">
      <XCircle class="h-10 w-10 text-red-500" aria-hidden="true" />
      <p class="text-sm text-red-600" role="alert">
        {{ state === "in_use" ? t("accountSecurity.confirm.inUse") : t("accountSecurity.confirm.failed") }}
      </p>
    </div>

    <RouterLink
      :to="auth.isAuthenticated ? '/settings' : '/login'"
      class="btn-gradient mt-2 w-full py-3 text-base"
    >
      {{ auth.isAuthenticated ? t("accountSecurity.confirm.toSettings") : t("auth.loginCta") }}
    </RouterLink>
  </AuthLayout>
</template>
