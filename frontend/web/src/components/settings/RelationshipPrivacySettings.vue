<script setup lang="ts">
// "How people find and contact you": graph's relationship privacy
// (GET/PATCH /social/settings/). Graph enforces every choice on its own reads.
import { onMounted, ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import { type ListVisibility, type RelationshipSettings, relationshipsService } from "@/services/relationships";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const toasts = useToastStore();
const uid = useId();

const value = ref<RelationshipSettings | null>(null);
const failed = ref(false);
const saving = ref<keyof RelationshipSettings | null>(null);

const LIST_LEVELS: ListVisibility[] = ["public", "friends", "only_me"];
const REQUEST_LEVELS: RelationshipSettings["friend_requests_from"][] = ["everyone", "friends_of_friends"];

const ROWS: { key: Exclude<keyof RelationshipSettings, "friend_requests_from">; label: string }[] = [
  { key: "friends_list_visibility", label: "friendsList" },
  { key: "follow_lists_visibility", label: "followLists" },
  { key: "counts_visibility", label: "counts" },
];

async function load() {
  failed.value = false;
  try {
    value.value = await relationshipsService.settings();
  } catch {
    failed.value = true;
  }
}

async function change<K extends keyof RelationshipSettings>(key: K, next: RelationshipSettings[K]) {
  if (!value.value || value.value[key] === next || saving.value) return;
  const before = value.value;
  value.value = { ...before, [key]: next };
  saving.value = key;
  try {
    value.value = await relationshipsService.updateSettings({ [key]: next } as Partial<RelationshipSettings>);
    toasts.success(t("settingsCenter.privacy.saved"));
  } catch (e) {
    value.value = before;
    toasts.error(e);
  } finally {
    saving.value = null;
  }
}

onMounted(load);
</script>

<template>
  <section id="relationships" class="card mb-4 scroll-mt-20 p-4" data-testid="privacy-connections">
    <h2 class="mb-1 font-semibold">{{ t("settingsCenter.privacy.findContact") }}</h2>
    <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("settingsCenter.privacy.connections") }}</p>
    <p v-if="failed" class="flex items-center justify-between gap-2 text-sm text-gray-500 dark:text-gray-400">
      {{ t("settingsCenter.privacy.loadFailed") }}
      <button type="button" class="btn-ghost text-sm" @click="load">{{ t("states.retry") }}</button>
    </p>
    <p v-else-if="!value" class="text-sm text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
    <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800">
      <li v-for="row in ROWS" :key="row.key" class="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
        <label :for="`${uid}-${row.key}`" class="text-sm">{{ t(`settingsCenter.privacy.${row.label}`) }}</label>
        <select
          :id="`${uid}-${row.key}`"
          class="input w-full sm:w-44"
          :value="value[row.key]"
          :disabled="saving !== null"
          :data-testid="`privacy-${row.key}`"
          @change="change(row.key, ($event.target as HTMLSelectElement).value as ListVisibility)"
        >
          <option v-for="lv in LIST_LEVELS" :key="lv" :value="lv">{{ t(`settingsCenter.privacy.listLevels.${lv}`) }}</option>
        </select>
      </li>
      <li class="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
        <label :for="`${uid}-requests`" class="text-sm">{{ t("settingsCenter.privacy.requestsFrom") }}</label>
        <select
          :id="`${uid}-requests`"
          class="input w-full sm:w-44"
          :value="value.friend_requests_from"
          :disabled="saving !== null"
          data-testid="privacy-friend_requests_from"
          @change="change('friend_requests_from', ($event.target as HTMLSelectElement).value as RelationshipSettings['friend_requests_from'])"
        >
          <option v-for="lv in REQUEST_LEVELS" :key="lv" :value="lv">{{ t(`settingsCenter.privacy.requestLevels.${lv}`) }}</option>
        </select>
      </li>
    </ul>
  </section>
</template>
