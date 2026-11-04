<script setup lang="ts">
// Profile basics (PATCH /profile/me/): name, intro, bio and place. The full
// editor (photos, work, education) lives on the profile page.
import { ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import { errorMessage } from "@/lib/errors";
import { profileService } from "@/services/profile";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();
const auth = useAuthStore();
const id = useId();

const form = ref({
  display_name: auth.profile?.display_name ?? "",
  intro: auth.profile?.intro ?? "",
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
    auth.profile = await profileService.update(form.value);
    message.value = t("settings.saved");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section id="profile-basics" class="card mb-4 scroll-mt-20 p-4">
    <h2 class="mb-3 font-semibold">{{ t("settingsCenter.account.quickEdit") }}</h2>
    <form class="space-y-3" @submit.prevent="save">
      <div>
        <label :for="`${id}-name`" class="mb-1 block text-sm font-medium">{{ t("auth.displayName") }}</label>
        <input :id="`${id}-name`" v-model="form.display_name" class="input" dir="auto" />
      </div>
      <div>
        <label :for="`${id}-intro`" class="mb-1 block text-sm font-medium">{{ t("settings.intro") }}</label>
        <input :id="`${id}-intro`" v-model="form.intro" class="input" dir="auto" maxlength="160" />
      </div>
      <div>
        <label :for="`${id}-bio`" class="mb-1 block text-sm font-medium">{{ t("profile.bioLabel") }}</label>
        <textarea :id="`${id}-bio`" v-model="form.bio" class="input min-h-[80px] resize-none" dir="auto" />
      </div>
      <div class="grid grid-cols-2 gap-3">
        <input v-model="form.city" class="input" dir="auto" :aria-label="t('profile.city')" :placeholder="t('profile.city')" />
        <input v-model="form.country" class="input" dir="auto" :aria-label="t('profile.country')" :placeholder="t('profile.country')" />
      </div>
      <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("settings.fullProfileHint") }}</p>
      <p v-if="message" class="text-sm text-green-600" role="status">{{ message }}</p>
      <p v-if="error" class="text-sm text-red-500" role="alert">{{ error }}</p>
      <button type="submit" class="btn-primary" :disabled="saving">{{ t("settings.save") }}</button>
    </form>
  </section>
</template>
