<script setup lang="ts">
import { Globe, Lock, UsersRound } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { categoryLabel } from "@/lib/search";
import { groupsService } from "@/services/groups";
import type { SearchResult } from "@/services/search";
import { useToastStore } from "@/stores/toasts";

// A private group shows its name and description only (the server sends nothing else).
const props = defineProps<{ result: SearchResult }>();
const { t, te } = useI18n();
const toasts = useToastStore();

const joined = ref<"none" | "member" | "pending">("none");
const busy = ref(false);

const name = computed(() => props.result.name || props.result.title);
const path = computed(() => `/groups/${encodeURIComponent(props.result.handle || props.result.id)}`);
const isPrivate = computed(() => props.result.privacy === "private");
const category = computed(() => {
  const raw = categoryLabel(props.result);
  return raw && te(`groups.categories.${raw}`) ? t(`groups.categories.${raw}`) : raw;
});

async function join() {
  if (busy.value || joined.value !== "none") return;
  busy.value = true;
  try {
    const membership = await groupsService.join(props.result.id);
    joined.value = membership?.state === "requested" ? "pending" : "member";
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <article class="card flex items-start gap-3 p-3 sm:p-4" data-testid="group-result">
    <RouterLink
      :to="path"
      class="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-tara-gradient-soft text-brand-600 ring-1 ring-brand-200/60 dark:text-brand-300 dark:ring-brand-900"
      tabindex="-1"
      aria-hidden="true"
    >
      <UsersRound class="h-7 w-7" />
    </RouterLink>
    <div class="min-w-0 flex-1">
      <RouterLink :to="path" class="block truncate font-semibold hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400" data-testid="group-result-name">
        <bdi>{{ name }}</bdi>
      </RouterLink>
      <p class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
        <span class="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-200" data-testid="group-privacy">
          <Lock v-if="isPrivate" class="h-3 w-3" aria-hidden="true" />
          <Globe v-else class="h-3 w-3" aria-hidden="true" />
          {{ t(`search.privacy.${isPrivate ? "private" : "public"}`) }}
        </span>
        <span v-if="category" dir="auto">{{ category }}</span>
        <span v-if="result.member_count != null">{{ t("search.members", result.member_count) }}</span>
      </p>
      <p v-if="result.description" class="mt-1 line-clamp-2 text-sm text-gray-600 dark:text-gray-300" dir="auto">{{ result.description }}</p>
    </div>
    <button
      v-if="joined === 'none'"
      type="button"
      class="btn-soft shrink-0 px-3 py-1.5"
      :aria-label="t('search.joinName', { name })"
      :disabled="busy"
      @click="join"
    >
      {{ t("search.join") }}
    </button>
    <span v-else class="shrink-0 rounded-xl bg-gray-100 px-3 py-1.5 text-sm font-semibold text-gray-700 dark:bg-gray-800 dark:text-gray-200">
      {{ joined === "pending" ? t("search.joinRequested") : t("search.joined") }}
    </span>
  </article>
</template>
