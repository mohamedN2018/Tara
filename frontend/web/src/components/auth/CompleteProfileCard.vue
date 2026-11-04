<script setup lang="ts">
// "Complete your profile" (plan 08 §1.1, track 1D): after sign-up and
// verification, the new account's first visits to /home offer a profile photo
// through the existing media upload. Dismissible; gone once a photo is set.
import { Camera, X } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { profileCompleted, profileToComplete } from "@/lib/completeProfile";
import { errorMessage, mediaErrorKey } from "@/lib/errors";
import { mediaService } from "@/services/media";
import { profileService } from "@/services/profile";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();
const auth = useAuthStore();

const dismissed = ref(false);
const uploading = ref(false);
const saved = ref(false);
const error = ref("");

const visible = computed(
  () =>
    !dismissed.value &&
    !!auth.profile &&
    profileToComplete(auth.account?.id) &&
    (saved.value || !auth.profile.avatar_media_id),
);

async function pick(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file || uploading.value) return;
  uploading.value = true;
  error.value = "";
  try {
    const media = await mediaService.upload(file, "image");
    auth.profile = await profileService.update({ avatar_media_id: media.id });
    saved.value = true;
  } catch (err) {
    const media = mediaErrorKey(err);
    error.value = media ? t(media) : errorMessage(err);
  } finally {
    uploading.value = false;
  }
}

function close() {
  profileCompleted();
  dismissed.value = true;
}
</script>

<template>
  <section
    v-if="visible"
    class="card relative overflow-hidden p-4"
    aria-labelledby="complete-profile-title"
    data-testid="complete-profile"
  >
    <div aria-hidden="true" class="pointer-events-none absolute inset-0 bg-tara-gradient-soft" />
    <button
      type="button"
      class="absolute end-2 top-2 rounded-full p-1.5 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
      :aria-label="t('register.complete.skip')"
      @click="close"
    >
      <X class="h-4 w-4" />
    </button>
    <div class="relative flex items-center gap-4">
      <UserAvatar :name="auth.profile?.display_name || '?'" :media-id="auth.profile?.avatar_media_id" :size="64" ring />
      <div class="min-w-0 flex-1 pe-6">
        <h2 id="complete-profile-title" class="font-display text-base font-bold text-gray-950 dark:text-white">
          {{ t("register.complete.title") }}
        </h2>
        <p class="text-sm text-gray-600 dark:text-gray-300" :role="saved ? 'status' : undefined">
          {{ saved ? t("register.complete.saved") : t("register.complete.body") }}
        </p>
      </div>
    </div>
    <p v-if="error" class="relative mt-2 text-sm text-red-600 dark:text-red-400" role="alert">{{ error }}</p>
    <div class="relative mt-3 flex flex-wrap items-center gap-2">
      <label class="btn-gradient cursor-pointer px-4 py-2 text-sm" :class="uploading ? 'pointer-events-none opacity-70' : ''">
        <Camera class="h-4 w-4" aria-hidden="true" />
        {{ uploading ? t("register.complete.uploading") : saved ? t("register.complete.change") : t("register.complete.add") }}
        <input type="file" accept="image/*" class="sr-only" :disabled="uploading" @change="pick" />
      </label>
      <button type="button" class="btn-ghost px-4 py-2 text-sm" @click="close">
        {{ saved ? t("register.complete.done") : t("register.complete.skip") }}
      </button>
    </div>
  </section>
</template>
