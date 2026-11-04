<script setup lang="ts">
// Deactivation (POST /me/deactivate/): re-authenticated with the password (or,
// for a Google-only account, the typed confirmation word). Every session ends;
// signing in again reactivates the account. Profile, post and search hide
// the account on account.deactivated. Deletion lives in DeleteAccount.vue.
import { onMounted, ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import ConfirmActionDialog from "@/components/social/ConfirmActionDialog.vue";
import { securityErrorKey } from "@/lib/securityErrors";
import { identityService } from "@/services/identity";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
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
  if (hasPassword.value ? !password.value : confirmWord.value.trim().toUpperCase() !== "DEACTIVATE") return;
  asking.value = true;
}

async function deactivate() {
  busy.value = true;
  error.value = "";
  try {
    await identityService.deactivate(password.value, confirmWord.value.trim());
    toasts.success(t("settingsCenter.deactivate.done"));
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
  <section id="deactivate" class="card mb-4 scroll-mt-20 p-4" data-testid="deactivate-account">
    <h2 class="font-semibold">{{ t("settingsCenter.deactivate.title") }}</h2>
    <p class="mb-3 mt-1 text-sm text-gray-600 dark:text-gray-300">{{ t("settingsCenter.deactivate.lead") }}</p>
    <form class="space-y-3" @submit.prevent="ask">
      <div v-if="hasPassword !== false">
        <label :for="`${id}-password`" class="label">{{ t("settingsCenter.deactivate.password") }}</label>
        <input :id="`${id}-password`" v-model="password" type="password" class="input" dir="ltr" autocomplete="current-password" required />
      </div>
      <div v-else>
        <label :for="`${id}-confirm`" class="label">{{ t("settingsCenter.deactivate.confirmWord") }}</label>
        <input :id="`${id}-confirm`" v-model="confirmWord" class="input" dir="ltr" autocomplete="off" required />
      </div>
      <p v-if="error" class="text-sm text-red-600 dark:text-red-400" role="alert">{{ error }}</p>
      <button type="submit" class="btn bg-red-700 text-white hover:bg-red-800" :disabled="busy || hasPassword === null" data-testid="deactivate-submit">
        {{ t("settingsCenter.deactivate.action") }}
      </button>
    </form>
    <ConfirmActionDialog
      v-if="asking"
      :title="t('settingsCenter.deactivate.confirmTitle')"
      :hint="t('settingsCenter.deactivate.confirmBody')"
      :confirm-label="t('settingsCenter.deactivate.confirm')"
      :busy="busy"
      @confirm="deactivate"
      @cancel="asking = false"
    />
  </section>
</template>
