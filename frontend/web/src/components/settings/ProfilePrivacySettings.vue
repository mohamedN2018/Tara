<script setup lang="ts">
// "Profile": who sees the profile, and each detail's own audience (profile
// service, PATCH /profile/me/ and /profile/me/privacy/). Moved here from the
// stand-alone privacy page (track T2) into the settings centre's Privacy section.
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import AudienceSelect from "@/components/profile/AudienceSelect.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { type FieldPrivacy, profileService } from "@/services/profile";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const toasts = useToastStore();

const VIS = ["public", "friends_only", "private"] as const;
const visibility = ref<string | null>(null);
const failed = ref(false);
const fields = ref<FieldPrivacy[] | null>(null);
const saving = ref("");

onMounted(async () => {
  await Promise.all([
    profileService
      .me()
      .then((p) => (visibility.value = p.visibility ?? "public"))
      .catch(() => (failed.value = true)),
    profileService
      .fieldPrivacy()
      .then((items) => (fields.value = items))
      .catch(() => (fields.value = null)),
  ]);
});

async function saveVisibility(next: string) {
  const before = visibility.value;
  visibility.value = next;
  saving.value = "visibility";
  try {
    visibility.value = (await profileService.update({ visibility: next })).visibility ?? next;
    toasts.success(t("people.privacy.saved"));
  } catch (e) {
    visibility.value = before;
    toasts.error(e);
  } finally {
    saving.value = "";
  }
}

async function saveField(key: string, next: string) {
  if (!fields.value) return;
  const before = fields.value.map((f) => ({ ...f }));
  fields.value = fields.value.map((f) => (f.field_key === key ? { ...f, visibility: next } : f));
  saving.value = `field:${key}`;
  try {
    await profileService.setFieldPrivacy(fields.value);
    toasts.success(t("people.privacy.saved"));
  } catch (e) {
    fields.value = before;
    toasts.error(e);
  } finally {
    saving.value = "";
  }
}
</script>

<template>
  <section id="profile" class="card mb-4 scroll-mt-20 p-4" aria-labelledby="pv-profile" data-testid="privacy-profile">
    <h2 id="pv-profile" class="font-semibold">{{ t("people.privacy.profile") }}</h2>
    <p v-if="failed" class="mt-2 text-sm text-gray-500 dark:text-gray-400">{{ t("people.privacy.loadFailed") }}</p>
    <LoadingSkeleton v-else-if="visibility === null" :rows="1" />
    <div v-else class="flex flex-col gap-2 border-b border-gray-100 py-3 sm:flex-row sm:items-center sm:justify-between dark:border-gray-800">
      <div>
        <label for="pv-visibility" class="text-sm font-medium">{{ t("people.privacy.visibility") }}</label>
        <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("people.privacy.visibilityHint") }}</p>
      </div>
      <select
        id="pv-visibility"
        :value="visibility"
        class="input w-full sm:w-44"
        :disabled="saving === 'visibility'"
        data-testid="privacy-visibility"
        @change="saveVisibility(($event.target as HTMLSelectElement).value)"
      >
        <option v-for="v in VIS" :key="v" :value="v">{{ t(`people.privacy.visibilityLevels.${v}`) }}</option>
      </select>
    </div>

    <template v-if="fields && fields.length">
      <h3 class="mt-3 text-sm font-semibold">{{ t("people.privacy.fields") }}</h3>
      <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("people.privacy.fieldsHint") }}</p>
      <ul class="divide-y divide-gray-100 dark:divide-gray-800">
        <li v-for="f in fields" :key="f.field_key" class="flex items-center justify-between gap-3 py-2 text-sm">
          <span>{{ t(`profile.privacyFields.${f.field_key}`) }}</span>
          <AudienceSelect
            :field="f.field_key"
            :model-value="f.visibility"
            :disabled="saving === `field:${f.field_key}`"
            @update:model-value="(v) => saveField(f.field_key, v)"
          />
        </li>
      </ul>
    </template>
  </section>
</template>
