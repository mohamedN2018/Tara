<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import { errorField, securityErrorKey } from "@/lib/securityErrors";
import { identityService } from "@/services/identity";

defineProps<{ hasPassword: boolean }>();

const { t } = useI18n();
const MIN_LENGTH = 10;

const form = ref({ current: "", next: "", confirm: "" });
const saving = ref(false);
const message = ref("");
const error = ref("");
const errorOn = ref<"current" | "next" | "confirm" | "">("");

async function submit() {
  if (saving.value) return;
  message.value = "";
  error.value = "";
  errorOn.value = "";
  if (form.value.next.length < MIN_LENGTH) {
    errorOn.value = "next";
    error.value = t("accountSecurity.errors.weakPassword");
    return;
  }
  if (form.value.next !== form.value.confirm) {
    errorOn.value = "confirm";
    error.value = t("accountSecurity.password.mismatch");
    return;
  }
  saving.value = true;
  try {
    await identityService.changePassword(form.value.current, form.value.next);
    form.value = { current: "", next: "", confirm: "" };
    message.value = t("accountSecurity.password.changed");
  } catch (e) {
    const field = errorField(e);
    errorOn.value = field === "current_password" ? "current" : field === "new_password" ? "next" : "";
    error.value = t(securityErrorKey(e));
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div>
    <h3 class="mb-2 text-sm font-semibold">{{ t("accountSecurity.password.title") }}</h3>

    <p v-if="!hasPassword" class="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-600 dark:bg-gray-800/60 dark:text-gray-300">
      {{ t("accountSecurity.password.none") }}
      <RouterLink to="/forgot-password" class="font-medium text-brand-600 dark:text-brand-300">
        {{ t("accountSecurity.password.setViaReset") }}
      </RouterLink>
    </p>

    <form v-else class="space-y-3" novalidate @submit.prevent="submit">
      <div>
        <label for="sec-current-password" class="label">{{ t("accountSecurity.password.current") }}</label>
        <input
          id="sec-current-password"
          v-model="form.current"
          type="password"
          dir="ltr"
          class="input"
          required
          autocomplete="current-password"
          :aria-invalid="errorOn === 'current'"
        />
      </div>
      <div>
        <label for="sec-new-password" class="label">{{ t("accountSecurity.password.new") }}</label>
        <input
          id="sec-new-password"
          v-model="form.next"
          type="password"
          dir="ltr"
          class="input"
          required
          :minlength="MIN_LENGTH"
          autocomplete="new-password"
          aria-describedby="sec-new-password-hint"
          :aria-invalid="errorOn === 'next'"
        />
        <p id="sec-new-password-hint" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
          {{ t("accountSecurity.password.hint") }}
        </p>
      </div>
      <div>
        <label for="sec-confirm-password" class="label">{{ t("accountSecurity.password.confirm") }}</label>
        <input
          id="sec-confirm-password"
          v-model="form.confirm"
          type="password"
          dir="ltr"
          class="input"
          required
          autocomplete="new-password"
          :aria-invalid="errorOn === 'confirm'"
        />
      </div>

      <p v-if="error" class="text-sm text-red-500" role="alert">{{ error }}</p>
      <p v-if="message" class="text-sm text-green-600 dark:text-green-400" role="status">{{ message }}</p>

      <button type="submit" class="btn-primary" :disabled="saving || !form.current">
        {{ saving ? t("accountSecurity.saving") : t("accountSecurity.password.submit") }}
      </button>
    </form>
  </div>
</template>
