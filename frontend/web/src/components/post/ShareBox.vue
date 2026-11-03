<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import MentionField from "@/components/post/MentionField.vue";
import { postService } from "@/services/post";
import { useToastStore } from "@/stores/toasts";
import type { Post } from "@/types";

const props = defineProps<{ post: Post }>();
const emit = defineEmits<{ cancel: []; shared: [post: Post] }>();

const { t } = useI18n();
const toasts = useToastStore();

// Widest first. A share can't reach further than the original.
const LEVELS = [
  { v: "public", label: "feed.audiencePublic" },
  { v: "followers", label: "feed.audienceFollowers" },
  { v: "friends", label: "feed.audienceFriends" },
  { v: "only_me", label: "feed.audienceOnlyMe" },
];
// A share points at the first post, so the limit is that post's audience.
const limit = computed(() => props.post.shared_post?.audience ?? props.post.audience);
const levels = computed(() => LEVELS.slice(Math.max(0, LEVELS.findIndex((l) => l.v === limit.value))));

const body = ref("");
const audience = ref(levels.value[0]?.v ?? "only_me");
const submitting = ref(false);

async function submit() {
  if (submitting.value) return;
  submitting.value = true;
  try {
    emit("shared", await postService.share(props.post.id, body.value.trim(), audience.value));
    toasts.success(t("post.shared"));
  } catch (e) {
    toasts.error(e);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <form class="mt-3 rounded-xl border border-gray-200 p-3 dark:border-gray-800" data-testid="share-box" @submit.prevent="submit">
    <MentionField
      v-model="body"
      multiline
      field-class="input min-h-16"
      :placeholder="t('post.sharePlaceholder')"
    />
    <div class="mt-2 flex items-center justify-between gap-2">
      <select v-model="audience" class="input w-auto" :aria-label="t('feed.audience')">
        <option v-for="l in levels" :key="l.v" :value="l.v">{{ t(l.label) }}</option>
      </select>
      <div class="flex gap-2">
        <button type="button" class="btn-ghost" @click="emit('cancel')">{{ t("feed.cancel") }}</button>
        <button type="submit" class="btn-primary" :disabled="submitting">{{ t("post.shareNow") }}</button>
      </div>
    </div>
  </form>
</template>
