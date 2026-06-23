<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";
import AppShell from "@/components/layout/AppShell.vue";
import { apiError } from "@/lib/api";
import { profileService } from "@/services/profile";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();
const auth = useAuthStore();

const form = ref({
  display_name: auth.profile?.display_name ?? "",
  bio: auth.profile?.bio ?? "",
  city: auth.profile?.city ?? "",
  country: auth.profile?.country ?? "",
});
const saving = ref(false);
const message = ref("");
const error = ref("");

async function save() {
  saving.value = true;
  message.value = "";
  error.value = "";
  try {
    const updated = await profileService.update(form.value);
    auth.profile = updated;
    message.value = t("settings.saved");
  } catch (e) {
    error.value = apiError(e).message;
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <AppShell>
    <h1 class="mb-4 text-xl font-bold">{{ t("settings.title") }}</h1>

    <section class="card mb-4 p-4">
      <h2 class="mb-3 font-semibold">{{ t("settings.appearance") }}</h2>
      <div class="flex items-center justify-between py-2">
        <span class="text-sm">{{ t("settings.theme") }}</span>
        <ThemeToggle />
      </div>
      <div class="flex items-center justify-between py-2">
        <span class="text-sm">{{ t("settings.language") }}</span>
        <LocaleToggle />
      </div>
    </section>

    <section class="card p-4">
      <h2 class="mb-3 font-semibold">{{ t("settings.account") }}</h2>
      <form class="space-y-3" @submit.prevent="save">
        <div>
          <label class="mb-1 block text-sm font-medium">{{ t("auth.displayName") }}</label>
          <input v-model="form.display_name" class="input" />
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium">{{ t("profile.about") }}</label>
          <textarea v-model="form.bio" class="input min-h-[80px] resize-none" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <input v-model="form.city" class="input" :placeholder="t('market.location')" />
          <input v-model="form.country" class="input" placeholder="Country" />
        </div>

        <p v-if="message" class="text-sm text-green-600">{{ message }}</p>
        <p v-if="error" class="text-sm text-red-500">{{ error }}</p>

        <button type="submit" class="btn-primary" :disabled="saving">{{ t("settings.save") }}</button>
      </form>
    </section>
  </AppShell>
</template>
