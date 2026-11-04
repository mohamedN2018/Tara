<script setup lang="ts">
import { MessageSquare, Share2, ThumbsUp } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { topReactions } from "@/lib/reactionCounts";
import ReactionPicker from "@/components/post/ReactionPicker.vue";
import { reactionByKey } from "@/lib/reactions";

const props = defineProps<{
  myReaction: string | null;
  reactionCount: number;
  reactionCounts?: Record<string, number>;
  commentCount: number;
  shareCount: number;
}>();
const emit = defineEmits<{
  react: [type: string];
  unreact: [];
  comment: [];
  share: [];
  reactions: [];
  shares: [];
}>();
const { t, locale } = useI18n();

// 74.9K / "74.9 ألف" like the reference, with Latin digits as everywhere else.
const compact = (n: number) =>
  n < 1000 ? String(n) : new Intl.NumberFormat(`${locale.value}-u-nu-latn`, { notation: "compact", maximumFractionDigits: 1 }).format(n);

const current = computed(() => reactionByKey(props.myReaction));
// The post's most used reactions; the viewer's own while counts are unknown.
const summaryEmojis = computed(() => {
  const top = topReactions(props.reactionCounts ?? {}).map((k) => reactionByKey(k)?.emoji ?? "👍");
  return top.length ? top : [current.value?.emoji ?? "👍"];
});

function toggleMain() {
  if (props.myReaction) emit("unreact");
  else emit("react", "like");
}
</script>

<template>
  <div>
    <!-- counts row (hidden when everything is zero) -->
    <div
      v-if="reactionCount || commentCount || shareCount"
      class="flex items-center justify-between gap-2 px-1 py-1 text-xs text-gray-500 dark:text-gray-400"
      data-testid="reaction-summary"
    >
      <button
        v-if="reactionCount"
        type="button"
        class="inline-flex items-center gap-1.5 rounded-full hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
        :aria-label="`${t('post.reactionsCount', reactionCount)} · ${t('post.reactionsTitle')}`"
        @click="emit('reactions')"
      >
        <span class="flex -space-x-1 rtl:space-x-reverse" aria-hidden="true">
          <span
            v-for="(emoji, i) in summaryEmojis"
            :key="i"
            class="flex h-5 w-5 items-center justify-center rounded-full bg-brand-50 text-[11px] leading-none ring-2 ring-white dark:bg-brand-950 dark:ring-gray-900"
          >{{ emoji }}</span>
        </span>
        <span class="tabular-nums" aria-hidden="true">{{ compact(reactionCount) }}</span>
      </button>
      <span v-else aria-hidden="true" />
      <span>
        <button v-if="commentCount" type="button" class="hover:underline" @click="emit('comment')">{{ t("post.commentsCount", commentCount) }}</button>
        <template v-if="commentCount && shareCount"> · </template>
        <button v-if="shareCount" type="button" class="hover:underline" @click="emit('shares')">{{ t("post.sharesCount", shareCount) }}</button>
      </span>
    </div>

    <div class="grid grid-cols-3 border-t border-gray-100 pt-1 text-sm dark:border-gray-800">
      <!-- Like + reaction picker (hover, long press, or ArrowUp) -->
      <ReactionPicker @pick="emit('react', $event)" @toggle="toggleMain">
        <template #default="pick">
          <button
            class="btn-ghost w-full justify-center"
            :class="current ? current.color + ' font-semibold' : ''"
            :aria-pressed="!!current"
            :aria-keyshortcuts="'ArrowUp'"
            @click="pick.onClick"
            @keydown="pick.onKeydown"
            @touchstart.passive="pick.onTouchstart"
            @touchend="pick.onTouchend"
          >
            <span v-if="current" class="text-lg leading-none">{{ current.emoji }}</span>
            <ThumbsUp v-else class="h-5 w-5" />
            {{ current ? t(current.labelKey) : t("post.like") }}
          </button>
        </template>
      </ReactionPicker>

      <button class="btn-ghost justify-center" @click="$emit('comment')">
        <MessageSquare class="h-5 w-5" /> {{ t("post.comment") }}
      </button>
      <button class="btn-ghost justify-center" @click="$emit('share')">
        <Share2 class="h-5 w-5" /> {{ t("post.share") }}
      </button>
    </div>
  </div>
</template>
