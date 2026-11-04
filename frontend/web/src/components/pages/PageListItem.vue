<script setup lang="ts">
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { type Page } from "@/services/pages";

import PageFollowButton from "./PageFollowButton.vue";

// One page in a list (Discover, Followed, Saved): avatar, name, category,
// followers and the Follow toggle (hidden for the page's own team).
defineProps<{ page: Page }>();
const emit = defineEmits<{ followChanged: [page: Page, following: boolean] }>();
const { t } = useI18n();
</script>

<template>
  <article class="card flex items-center gap-3 p-3" data-testid="page-list-item">
    <RouterLink :to="{ name: 'page', params: { handle: page.handle } }" class="shrink-0" :aria-label="page.name">
      <UserAvatar :name="page.name" :media-id="page.avatar_media_id" :size="56" />
    </RouterLink>
    <div class="min-w-0 flex-1">
      <RouterLink :to="{ name: 'page', params: { handle: page.handle } }" class="block truncate font-bold hover:underline" data-testid="page-list-name">
        <bdi>{{ page.name }}</bdi>
      </RouterLink>
      <p class="truncate text-xs text-gray-500 dark:text-gray-400">
        <span v-if="page.category" dir="auto">{{ page.category }}</span>
        <template v-if="page.category && page.followers_count !== null"> · </template>
        <span v-if="page.followers_count !== null">{{ t("pageHub.card.followers", { count: page.followers_count }, page.followers_count) }}</span>
      </p>
      <span v-if="page.my_role" class="mt-1 inline-block rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-700 dark:bg-brand-950 dark:text-brand-300">
        {{ t(`pages.roles.${page.my_role}`) }}
      </span>
    </div>
    <PageFollowButton
      v-if="!page.my_role && page.viewer_following !== null"
      :page-id="page.id"
      :name="page.name"
      :following="page.viewer_following"
      compact
      @changed="emit('followChanged', page, $event)"
    />
  </article>
</template>
