<script setup lang="ts">
import { ArrowLeft } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import PostCard from "@/components/post/PostCard.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { postService } from "@/services/post";
import type { Post } from "@/types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();

// `?comment=<id>` (notification links) and optionally `?thread=<root id>`.
const ID_RE = /^[0-9a-f-]{8,64}$/i;
const queryId = (key: string) => {
  const v = route.query[key];
  return typeof v === "string" && ID_RE.test(v) ? v : null;
};
const focusCommentId = computed(() => queryId("comment"));
const focusThreadId = computed(() => queryId("thread"));

const post = ref<Post | null>(null);
const loading = ref(true);
const error = ref(false);

async function load() {
  loading.value = true;
  error.value = false;
  try {
    post.value = await postService.get(route.params.id as string);
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

function onRemoved() {
  router.back();
}

watch(() => route.params.id, load);
onMounted(load);
</script>

<template>
  <AppShell :right="false">
    <div class="mx-auto w-full max-w-[600px] space-y-4">
      <button class="btn-ghost" @click="router.back()">
        <ArrowLeft class="h-4 w-4 rtl:rotate-180" /> {{ t("states.back") }}
      </button>
      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error || !post" @retry="load" />
      <PostCard
        v-else
        :key="post.id"
        :post="post"
        :start-comments-open="true"
        :focus-comment-id="focusCommentId"
        :focus-thread-id="focusThreadId"
        @removed="onRemoved"
      />
    </div>
  </AppShell>
</template>
