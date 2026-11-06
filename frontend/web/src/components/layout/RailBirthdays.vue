<script setup lang="ts">
import { Gift } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { birthdaysService, type FriendBirthday } from "@/services/birthdays";
import { useDirectoryStore } from "@/stores/directory";
import { railsReady } from "@/lib/delivery";

import { railHeading, railSection } from "./rightRail";

// "Birthdays" in the right column: friends whose birthday is today, as identity
// shares them (only friends who show their birthday to friends, no blocks).
// Hidden when nobody has a birthday today or identity can't answer.
const { t } = useI18n();
const directory = useDirectoryStore();
const today = ref<FriendBirthday[]>([]);
const heading = railHeading;

const first = computed(() => today.value[0]?.account_id ?? "");
const second = computed(() => today.value[1]?.account_id ?? "");
const keypath = computed(() =>
  today.value.length === 1 ? "socialShell.birthdays.railOne" : today.value.length === 2 ? "socialShell.birthdays.railTwo" : "socialShell.birthdays.railMany",
);

// Home holds the rails until its first post is on screen (08 §7.4); elsewhere they start at once.
onMounted(async () => {
  await railsReady();
  today.value = await birthdaysService
    .list(1)
    .then((rows) => rows.filter((r) => r.days_until === 0))
    .catch(() => []);
});
</script>

<template>
  <section v-if="today.length" :class="railSection" aria-labelledby="rs-birthdays" data-testid="rail-birthdays">
    <h2 id="rs-birthdays" :class="heading">{{ t("socialShell.birthdays.title") }}</h2>
    <RouterLink
      :to="{ path: '/friends', query: { tab: 'birthdays' } }"
      class="flex items-start gap-3 rounded-xl p-2 text-sm transition hover:bg-gray-200/60 dark:hover:bg-gray-800/60"
      data-testid="rail-birthdays-link"
    >
      <Gift class="mt-0.5 h-6 w-6 shrink-0 text-accent-700 dark:text-accent-300" aria-hidden="true" />
      <i18n-t :keypath="keypath" tag="span" scope="global" class="min-w-0 flex-1 text-gray-800 dark:text-gray-200">
        <template #name><bdi class="font-semibold">{{ directory.label(first) }}</bdi></template>
        <template #other><bdi class="font-semibold">{{ directory.label(second) }}</bdi></template>
        <template #count>{{ today.length - 1 }}</template>
      </i18n-t>
    </RouterLink>
  </section>
</template>
