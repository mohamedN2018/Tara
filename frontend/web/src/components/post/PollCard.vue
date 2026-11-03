<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { postService } from "@/services/post";
import { useToastStore } from "@/stores/toasts";
import type { Poll } from "@/types";

const props = defineProps<{ postId: string; poll: Poll }>();

const { t } = useI18n();
const toasts = useToastStore();
const current = ref<Poll>(props.poll);
const voting = ref(false);

const showResults = computed(() => !!current.value.my_option_id || current.value.closed);
const percent = (votes: number) =>
  current.value.total_votes ? Math.round((votes / current.value.total_votes) * 100) : 0;

async function vote(optionId: string) {
  if (voting.value || showResults.value) return;
  voting.value = true;
  try {
    const updated = await postService.vote(props.postId, optionId);
    if (updated.poll) current.value = updated.poll;
  } catch (e) {
    toasts.error(e);
  } finally {
    voting.value = false;
  }
}
</script>

<template>
  <div class="mt-3 space-y-2" data-testid="poll">
    <template v-for="option in current.options" :key="option.id">
      <div
        v-if="showResults"
        class="relative overflow-hidden rounded-lg border border-gray-200 px-3 py-2 text-sm dark:border-gray-700"
        :class="current.my_option_id === option.id ? 'border-brand-400' : ''"
      >
        <div class="absolute inset-y-0 start-0 bg-brand-100 dark:bg-brand-950/60" :style="{ width: `${percent(option.vote_count)}%` }" />
        <div class="relative flex items-center justify-between gap-2">
          <span class="min-w-0 break-words" dir="auto">{{ option.text }}</span>
          <span class="shrink-0 text-xs font-semibold tabular-nums">{{ percent(option.vote_count) }}%</span>
        </div>
      </div>
      <button
        v-else
        class="w-full rounded-lg border border-gray-200 px-3 py-2 text-start text-sm transition hover:border-brand-400 hover:bg-brand-50 disabled:opacity-60 dark:border-gray-700 dark:hover:bg-brand-950/40"
        :disabled="voting"
        dir="auto"
        @click="vote(option.id)"
      >
        {{ option.text }}
      </button>
    </template>
    <p class="text-xs text-gray-500 dark:text-gray-400">
      {{ t("post.pollVotes", current.total_votes) }}
      <template v-if="current.closed"> · {{ t("post.pollClosed") }}</template>
    </p>
  </div>
</template>
