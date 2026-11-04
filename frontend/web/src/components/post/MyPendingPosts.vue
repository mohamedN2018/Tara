<script setup lang="ts">
import { Clock } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import PostCard from "@/components/post/PostCard.vue";
import { type Group, groupPostsService } from "@/services/groups";
import type { Post } from "@/types";

// A member's own posts waiting for approval in a group: "You have N posts
// pending approval · Manage". The server returns only the viewer's own pending
// posts to a non-reviewer, so nobody else's waiting posts can show here. The
// author can delete one from its menu while it waits.
const props = withDefaults(defineProps<{ group: Group; version?: number }>(), { version: 0 });

const { t } = useI18n();
const posts = ref<Post[]>([]);
const open = ref(false);
let generation = 0;

async function refresh() {
  const run = ++generation;
  try {
    const page = await groupPostsService.feed(props.group.id, "pending");
    if (run === generation) posts.value = page.data;
  } catch {
    if (run === generation) posts.value = [];
  }
}

function onRemoved(id: string) {
  posts.value = posts.value.filter((p) => p.id !== id);
}

onMounted(refresh);
watch(() => [props.group.id, props.version], refresh);
defineExpose({ refresh });
</script>

<template>
  <section v-if="posts.length" class="card p-3 sm:p-4" aria-labelledby="my-pending-title" data-testid="my-pending-posts">
    <div class="flex items-center gap-3">
      <span class="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600 dark:bg-brand-950/60 dark:text-brand-300">
        <Clock class="h-5 w-5" aria-hidden="true" />
      </span>
      <p id="my-pending-title" class="min-w-0 flex-1 text-sm font-semibold">
        {{ t("postsFeed.pending.banner", { n: posts.length }, posts.length) }}
      </p>
      <button type="button" class="btn-ghost shrink-0" :aria-expanded="open" data-testid="my-pending-toggle" @click="open = !open">
        {{ open ? t("postsFeed.pending.hide") : t("postsFeed.pending.manage") }}
      </button>
    </div>
    <div v-if="open" class="mt-3 space-y-3">
      <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("postsFeed.pending.hint") }}</p>
      <h3 class="sr-only">{{ t("postsFeed.pending.title") }}</h3>
      <PostCard v-for="p in posts" :key="p.id" :post="p" @removed="onRemoved" />
    </div>
  </section>
</template>
