<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import { errorField, securityErrorKey } from "@/lib/securityErrors";
import { identityService, type SecurityOverview } from "@/services/identity";
import { useToastStore } from "@/stores/toasts";

const props = defineProps<{ overview: SecurityOverview }>();
const emit = defineEmits<{ changed: [] }>();

const { t } = useI18n();
const toasts = useToastStore();

const newEmail = ref("");
const password = ref("");
const saving = ref(false);
const sentTo = ref("");
const error = ref("");
const errorOn = ref<"new_email" | "password" | "">("");

async function submit() {
  if (saving.value) return;
  saving.value = true;
  error.value = "";
  errorOn.value = "";
  sentTo.value = "";
  try {
    sentTo.value = await identityService.requestEmailChange(newEmail.value.trim(), password.value);
    newEmail.value = "";
    password.value = "";
    emit("changed");
  } catch (e) {
    const field = errorField(e);
    errorOn.value = field === "new_email" || field === "password" ? field : "";
    error.value = t(securityErrorKey(e));
  } finally {
    saving.value = false;
  }
}

async function cancel() {
  try {
    await identityService.cancelEmailChange();
    sentTo.value = "";
    emit("changed");
  } catch (e) {
    toasts.error(e);
  }
}
</script>

<template>
  <div>
    <h3 class="mb-2 text-sm font-semibold">{{ t("accountSecurity.email.title") }}</h3>

    <div class="mb-3 flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2 text-sm dark:bg-gray-800/60">
      <span class="min-w-0">
        <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t("accountSecurity.email.current") }}</span>
        <bdi class="block truncate" dir="ltr">{{ props.overview.email }}</bdi>
      </span>
    </div>

    <div
      v-if="props.overview.pending_email"
      class="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
      role="status"
    >
      <span class="min-w-0">
        {{ t("accountSecurity.email.pending") }}
        <bdi dir="ltr" class="font-medium">{{ props.overview.pending_email }}</bdi>
      </span>
      <button type="button" class="btn-ghost text-sm" @click="cancel">{{ t("accountSecurity.email.cancel") }}</button>
    </div>

    <p v-if="!props.overview.has_password" class="text-sm text-gray-600 dark:text-gray-300">
      {{ t("accountSecurity.email.needsPassword") }}
    </p>

    <form v-else class="space-y-3" novalidate @submit.prevent="submit">
      <div>
        <label for="sec-new-email" class="label">{{ t("accountSecurity.email.new") }}</label>
        <input
          id="sec-new-email"
          v-model="newEmail"
          type="email"
          dir="ltr"
          class="input"
          required
          autocomplete="email"
          :aria-invalid="errorOn === 'new_email'"
        />
      </div>
      <div>
        <label for="sec-email-password" class="label">{{ t("accountSecurity.email.password") }}</label>
        <input
          id="sec-email-password"
          v-model="password"
          type="password"
          dir="ltr"
          class="input"
          required
          autocomplete="current-password"
          :aria-invalid="errorOn === 'password'"
        />
      </div>

      <p v-if="error" class="text-sm text-red-500" role="alert">{{ error }}</p>
      <p v-if="sentTo" class="text-sm text-green-600 dark:text-green-400" role="status">
        {{ t("accountSecurity.email.sent") }} <bdi dir="ltr" class="font-medium">{{ sentTo }}</bdi>
      </p>

      <button type="submit" class="btn-primary" :disabled="saving || !newEmail || !password">
        {{ saving ? t("accountSecurity.saving") : t("accountSecurity.email.submit") }}
      </button>
    </form>
  </div>
</template>
