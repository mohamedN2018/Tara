<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { composerService, TAG_POLICIES, type TagPolicy } from "@/services/composer";
import { useToastStore } from "@/stores/toasts";

// "Who can tag me in posts?" (2C). Kept by the post service, which enforces it
// on every tag; this only reads and sets it.
const { t } = useI18n();
const toasts = useToastStore();

const value = ref<TagPolicy | null>(null);
const unavailable = ref(false);
const saving = ref(false);

onMounted(async () => {
  try {
    value.value = (await composerService.settings()).who_can_tag;
  } catch {
    unavailable.value = true;
  }
});

async function choose(next: TagPolicy) {
  if (saving.value || next === value.value) return;
  const before = value.value;
  value.value = next;
  saving.value = true;
  try {
    value.value = (await composerService.setWhoCanTag(next)).who_can_tag;
    toasts.success(t("composer.settings.saved"));
  } catch (err) {
    value.value = before;
    toasts.error(err);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section id="tags" class="card mb-4 scroll-mt-20 p-4" data-testid="tag-privacy">
    <h2 class="mb-1 font-semibold">{{ t("composer.settings.title") }}</h2>
    <p v-if="unavailable" class="text-sm text-gray-500 dark:text-gray-400">{{ t("composer.settings.unavailable") }}</p>
    <fieldset v-else :disabled="value === null || saving">
      <legend class="mb-2 text-sm text-gray-700 dark:text-gray-300">{{ t("composer.settings.whoCanTag") }}</legend>
      <div class="flex flex-wrap gap-2">
        <label
          v-for="p in TAG_POLICIES"
          :key="p"
          class="chip cursor-pointer focus-within:ring-2 focus-within:ring-brand-400"
          :class="value === p ? 'chip-active' : ''"
        >
          <input type="radio" name="who-can-tag" class="sr-only" :value="p" :checked="value === p" @change="choose(p)" />
          {{ t(`composer.settings.${p}`) }}
        </label>
      </div>
      <p class="mt-2 text-xs text-gray-500 dark:text-gray-400">{{ t("composer.settings.hint") }}</p>
    </fieldset>
  </section>
</template>
