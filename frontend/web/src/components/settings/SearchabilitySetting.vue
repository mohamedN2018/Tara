<script setup lang="ts">
// "Let people find me in search" (spec B): the profile's `searchable` flag
// (PATCH /profile/me/). Profile announces it in `profile.updated`; search then
// drops or re-adds the person, and graph's suggestions skip them.
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { profileService } from "@/services/profile";
import { useToastStore } from "@/stores/toasts";

import SettingSwitch from "./SettingSwitch.vue";

const { t } = useI18n();
const toasts = useToastStore();

const value = ref<boolean | null>(null);
const failed = ref(false);
const saving = ref(false);

onMounted(async () => {
  try {
    value.value = (await profileService.me()).searchable ?? true;
  } catch {
    failed.value = true;
  }
});

async function save(next: boolean) {
  if (saving.value || value.value === null) return;
  const before = value.value;
  value.value = next;
  saving.value = true;
  try {
    value.value = (await profileService.update({ searchable: next })).searchable ?? next;
    toasts.success(t("discoverability.saved"));
  } catch (e) {
    value.value = before;
    toasts.error(e);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section id="search" class="card mb-4 scroll-mt-20 p-4" aria-labelledby="pv-search" data-testid="privacy-searchable">
    <h2 id="pv-search" class="mb-1 font-semibold">{{ t("discoverability.title") }}</h2>
    <p v-if="failed" class="text-sm text-gray-500 dark:text-gray-400">{{ t("discoverability.unavailable") }}</p>
    <LoadingSkeleton v-else-if="value === null" :rows="1" />
    <SettingSwitch
      v-else
      :model-value="value"
      :label="t('discoverability.label')"
      :hint="t('discoverability.hint')"
      :disabled="saving"
      testid="privacy-searchable-switch"
      @update:model-value="save"
    />
  </section>
</template>
