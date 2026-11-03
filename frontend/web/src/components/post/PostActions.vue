<script setup lang="ts">
import { MessageSquare, Share2, ThumbsUp } from "lucide-vue-next";
import { computed, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";

import { REACTIONS, reactionByKey } from "@/lib/reactions";

const props = defineProps<{
  myReaction: string | null;
  reactionCount: number;
  commentCount: number;
  shareCount: number;
}>();
const emit = defineEmits<{ react: [type: string]; unreact: []; comment: []; share: [] }>();
const { t } = useI18n();

const current = computed(() => reactionByKey(props.myReaction));
const summaryEmoji = computed(() => current.value?.emoji ?? "👍");

// --- Reaction picker: hover (desktop) + long-press (touch). ---
const pickerOpen = ref(false);
let openTimer: number | undefined;
let closeTimer: number | undefined;
let pressTimer: number | undefined;
let suppressClick = false;

function openSoon() {
  window.clearTimeout(closeTimer);
  openTimer = window.setTimeout(() => (pickerOpen.value = true), 300);
}
function closeSoon() {
  window.clearTimeout(openTimer);
  closeTimer = window.setTimeout(() => (pickerOpen.value = false), 250);
}
function cancelClose() {
  window.clearTimeout(closeTimer);
}
function choose(type: string) {
  pickerOpen.value = false;
  emit("react", type);
}
function toggleMain() {
  if (suppressClick) {
    suppressClick = false;
    return;
  }
  if (props.myReaction) emit("unreact");
  else emit("react", "like");
}
function touchStart() {
  pressTimer = window.setTimeout(() => {
    pickerOpen.value = true;
    suppressClick = true;
  }, 400);
}
function touchEnd() {
  window.clearTimeout(pressTimer);
}

onBeforeUnmount(() => {
  window.clearTimeout(openTimer);
  window.clearTimeout(closeTimer);
  window.clearTimeout(pressTimer);
});
</script>

<template>
  <div>
    <!-- counts row (hidden when everything is zero) -->
    <div
      v-if="reactionCount || commentCount || shareCount"
      class="flex items-center justify-between px-1 py-1 text-xs text-gray-500"
    >
      <span v-if="reactionCount" class="inline-flex items-center gap-1">
        <span class="text-sm leading-none" aria-hidden="true">{{ summaryEmoji }}</span>
        <span :aria-label="t('post.reactionsCount', reactionCount)">{{ reactionCount }}</span>
      </span>
      <span v-else aria-hidden="true" />
      <span>
        <template v-if="commentCount">{{ t("post.commentsCount", commentCount) }}</template>
        <template v-if="commentCount && shareCount"> · </template>
        <template v-if="shareCount">{{ t("post.sharesCount", shareCount) }}</template>
      </span>
    </div>

    <div class="grid grid-cols-3 border-t border-gray-100 pt-1 text-sm dark:border-gray-800">
      <!-- Like + reaction picker -->
      <div class="relative" @mouseenter="openSoon" @mouseleave="closeSoon">
        <template v-if="pickerOpen">
          <div class="fixed inset-0 z-40" @click="pickerOpen = false" />
        </template>
        <div
          v-if="pickerOpen"
          class="absolute bottom-full start-0 z-50 mb-2 flex items-center gap-1 rounded-full border border-gray-100 bg-white px-2 py-1.5 shadow-lg dark:border-gray-700 dark:bg-gray-800"
          @mouseenter="cancelClose"
          @mouseleave="closeSoon"
        >
          <button
            v-for="r in REACTIONS"
            :key="r.key"
            type="button"
            class="text-2xl leading-none transition hover:-translate-y-1 hover:scale-125"
            :title="t(r.labelKey)"
            :aria-label="t(r.labelKey)"
            @click="choose(r.key)"
          >
            {{ r.emoji }}
          </button>
        </div>

        <button
          class="btn-ghost w-full justify-center"
          :class="current ? current.color + ' font-semibold' : ''"
          :aria-pressed="!!current"
          @click="toggleMain"
          @touchstart.passive="touchStart"
          @touchend="touchEnd"
        >
          <span v-if="current" class="text-lg leading-none">{{ current.emoji }}</span>
          <ThumbsUp v-else class="h-5 w-5" />
          {{ current ? t(current.labelKey) : t("post.like") }}
        </button>
      </div>

      <button class="btn-ghost justify-center" @click="$emit('comment')">
        <MessageSquare class="h-5 w-5" /> {{ t("post.comment") }}
      </button>
      <button class="btn-ghost justify-center" @click="$emit('share')">
        <Share2 class="h-5 w-5" /> {{ t("post.share") }}
      </button>
    </div>
  </div>
</template>
