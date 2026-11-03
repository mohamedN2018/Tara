<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { categoryLabel } from "@/lib/search";
import { graphService } from "@/services/graph";
import type { SearchResult } from "@/services/search";
import { useToastStore } from "@/stores/toasts";

const props = defineProps<{ result: SearchResult }>();
const { t } = useI18n();
const toasts = useToastStore();

const following = ref(!!props.result.following);
watch(() => props.result.following, (v) => (following.value = !!v));
const followers = ref<number | null>(props.result.followers_count ?? null);
watch(() => props.result.followers_count, (v) => (followers.value = v ?? null));
const busy = ref(false);

const name = computed(() => props.result.name || props.result.title);
const category = computed(() => categoryLabel(props.result));
const to = computed(() =>
  props.result.handle ? { name: "page", params: { handle: props.result.handle } } : { name: "pages" },
);

async function toggle() {
  if (busy.value) return;
  busy.value = true;
  const next = !following.value;
  try {
    if (next) await graphService.followPage(props.result.id);
    else await graphService.unfollowPage(props.result.id);
    following.value = next;
    if (followers.value !== null) followers.value = Math.max(0, followers.value + (next ? 1 : -1));
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <article class="card flex items-center gap-3 p-3 sm:p-4" data-testid="page-result">
    <RouterLink :to="to" class="shrink-0" tabindex="-1" aria-hidden="true">
      <UserAvatar :name="name" :media-id="result.avatar_media_id" :size="56" />
    </RouterLink>
    <div class="min-w-0 flex-1">
      <RouterLink :to="to" class="block truncate font-semibold hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400" dir="auto">
        {{ name }}
      </RouterLink>
      <p class="truncate text-xs text-gray-500 dark:text-gray-400">
        <span v-if="category" dir="auto">{{ category }}</span>
        <span v-if="category && followers !== null" aria-hidden="true"> · </span>
        <span v-if="followers !== null">{{ t("search.followers", followers) }}</span>
      </p>
    </div>
    <button
      type="button"
      class="shrink-0 px-3 py-1.5"
      :class="following ? 'btn-outline' : 'btn-soft'"
      :aria-pressed="following"
      :aria-label="following ? t('search.unfollow', { name }) : t('search.followName', { name })"
      :disabled="busy"
      @click="toggle"
    >
      {{ following ? t("search.following") : t("search.follow") }}
    </button>
  </article>
</template>
