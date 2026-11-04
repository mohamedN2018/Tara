<script setup lang="ts">
import { Ban } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import type { Suspension } from "@/services/moderation";

/**
 * Shown on the sign-in card when the account is suspended: until when (or
 * that it has no end date) and whether it followed a Community Standards
 * decision. The staff's own note is never sent to the member.
 */
const props = defineProps<{ suspension: Suspension }>();
const { t, locale } = useI18n();

const until = computed(() =>
  props.suspension.until
    ? new Intl.DateTimeFormat(locale.value, { dateStyle: "long", timeStyle: "short" }).format(new Date(props.suspension.until))
    : "",
);
</script>

<template>
  <div class="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100" role="alert" data-testid="suspended-notice">
    <p class="flex items-center gap-2 font-bold">
      <Ban class="h-5 w-5 shrink-0" aria-hidden="true" />
      {{ t("safety.suspended.title") }}
    </p>
    <p class="mt-1">
      <template v-if="until">{{ t("safety.suspended.until", { date: until }) }}</template>
      <template v-else>{{ t("safety.suspended.noEnd") }}</template>
    </p>
    <p class="mt-1">{{ t(suspension.source === "moderation" ? "safety.suspended.byModeration" : "safety.suspended.byTeam") }}</p>
    <RouterLink to="/legal/community-standards" class="mt-2 inline-block font-semibold underline">{{ t("safety.standards.learn") }}</RouterLink>
  </div>
</template>
