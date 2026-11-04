<script setup lang="ts">
// Delete account (POST /me/delete/): re-authenticated like deactivation (the
// password, or for a Google-only account the typed confirmation word). The
// account is hidden and signed out at once and erased by identity's beat task
// after the grace period; signing in before then cancels the deletion.
import { onMounted, ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import ConfirmActionDialog from "@/components/social/ConfirmActionDialog.vue";
import { securityErrorKey } from "@/lib/securityErrors";
import { identityService } from "@/services/identity";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";

// Mirrors identity's account_center.DELETION_GRACE.
const GRACE_DAYS = 30;

const { t, locale } = useI18n();
const auth = useAuthStore();
const toasts = useToastStore();
const id = useId();

const hasPassword = ref<boolean | null>(null);
const password = ref("");
const confirmWord = ref("");
const asking = ref(false);
const busy = ref(false);
const error = ref("");

onMounted(async () => {
  try {
    hasPassword.value = (await identityService.security()).has_password;
  } catch {
    hasPassword.value = true; // the server checks again either way
  }
});

function ask() {
  error.value = "";
  if (hasPassword.value ? !password.value : confirmWord.value.trim().toUpperCase() !== "DELETE") return;
  asking.value = true;
}

async function remove() {
  busy.value = true;
  error.value = "";
  try {
    const { deletion_scheduled_for } = await identityService.deleteAccount(password.value, confirmWord.value.trim());
    const date = new Intl.DateTimeFormat(locale.value, { dateStyle: "long" }).format(new Date(deletion_scheduled_for));
    toasts.success(t("settingsCenter.deleteAccount.done", { date }));
    // Every session is already revoked server-side: leave without another call.
    await auth.logout({ remote: false });
  } catch (e) {
    asking.value = false;
    error.value = t(securityErrorKey(e));
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section id="delete" class="card mb-4 scroll-mt-20 p-4" data-testid="delete-account">
    <h2 class="font-semibold">{{ t("settingsCenter.deleteAccount.title") }}</h2>
    <p class="mt-1 text-sm text-gray-600 dark:text-gray-300">{{ t("settingsCenter.deleteAccount.lead", { days: GRACE_DAYS }) }}</p>
    <p class="mb-3 mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t("settingsCenter.deleteAccount.erased") }}</p>
    <form class="space-y-3" @submit.prevent="ask">
      <div v-if="hasPassword !== false">
        <label :for="`${id}-password`" class="label">{{ t("settingsCenter.deleteAccount.password") }}</label>
        <input :id="`${id}-password`" v-model="password" type="password" class="input" dir="ltr" autocomplete="current-password" required />
      </div>
      <div v-else>
        <label :for="`${id}-confirm`" class="label">{{ t("settingsCenter.deleteAccount.confirmWord") }}</label>
        <input :id="`${id}-confirm`" v-model="confirmWord" class="input" dir="ltr" autocomplete="off" required />
      </div>
      <p v-if="error" class="text-sm text-red-600 dark:text-red-400" role="alert">{{ error }}</p>
      <button type="submit" class="btn bg-red-700 text-white hover:bg-red-800" :disabled="busy || hasPassword === null" data-testid="delete-submit">
        {{ t("settingsCenter.deleteAccount.action") }}
      </button>
    </form>
    <ConfirmActionDialog
      v-if="asking"
      :title="t('settingsCenter.deleteAccount.confirmTitle')"
      :hint="t('settingsCenter.deleteAccount.confirmBody', { days: GRACE_DAYS })"
      :confirm-label="t('settingsCenter.deleteAccount.confirm')"
      :busy="busy"
      @confirm="remove"
      @cancel="asking = false"
    />
  </section>
</template>
