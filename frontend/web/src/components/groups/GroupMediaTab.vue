<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { type Group, groupPostsService } from "@/services/groups";
import { useToastStore } from "@/stores/toasts";
import type { Post } from "@/types";

import GroupMediaTile from "./GroupMediaTile.vue";

// Photos from the group's posts. URLs are minted by the post service only for
// people who may read the group, so this only renders for them.
const props = defineProps<{ group: Group }>();

const { t } = useI18n();
const toasts = useToastStore();
const posts = ref<Post[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);

const tiles = computed(() => posts.value.flatMap((p) => p.media_ids.map((id) => ({ id, post: p.id }))));

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const page = await groupPostsService.feed(props.group.id, "media");
    posts.value = page.data;
    cursor.value = page.page.next_cursor;
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

async function loadMore() {
  if (!cursor.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await groupPostsService.feed(props.group.id, "media", cursor.value);
    posts.value = [...posts.value, ...page.data];
    cursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="card p-4">
    <LoadingSkeleton v-if="loading" :rows="2" />
    <ErrorState v-else-if="error" @retry="load" />
    <EmptyState v-else-if="!tiles.length">{{ t("groups.empty.media") }}</EmptyState>
    <template v-else>
      <ul class="grid grid-cols-3 gap-1.5 sm:grid-cols-4">
        <GroupMediaTile
          v-for="(tile, i) in tiles"
          :key="tile.id"
          :media-id="tile.id"
          :post-id="tile.post"
          :label="t('groups.mediaOpen', { n: i + 1 })"
        />
      </ul>
      <button v-if="cursor" class="btn-ghost mx-auto mt-3 block" :disabled="loadingMore" @click="loadMore">
        {{ loadingMore ? t("states.loading") : t("states.loadMore") }}
      </button>
    </template>
  </div>
</template>
