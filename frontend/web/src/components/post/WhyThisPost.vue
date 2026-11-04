<script setup lang="ts">
import { Info, Settings2, X } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import type { FeedReason } from "@/services/feed";

// "Why am I seeing this post?": the feed's own reason for the item (self,
// friend or follow) and the sort the viewer picked. Nothing is guessed.
const props = withDefaults(
  defineProps<{ reason: FeedReason; name: string; page?: boolean; mode?: string | null }>(),
  { page: false, mode: null },
);
const emit = defineEmits<{ close: [] }>();

const { t } = useI18n();
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
useEscapeKey(ref(true), () => emit("close"));

const line = computed(() => {
  if (props.reason === "self") return t("postsFeed.why.self");
  if (props.reason === "friend") return t("postsFeed.why.friend", { name: props.name });
  return t(props.page ? "postsFeed.why.page" : "postsFeed.why.follow", { name: props.name });
});
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[60] flex items-end justify-center bg-gray-950/60 backdrop-blur-sm sm:items-center sm:p-4">
      <div class="fixed inset-0" aria-hidden="true" @click="emit('close')" />
      <div
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="why-post-title"
        tabindex="-1"
        class="card relative z-10 w-full animate-pop-in rounded-b-none rounded-t-2xl p-0 shadow-pop sm:max-w-md sm:rounded-2xl"
        data-testid="why-post"
      >
        <div class="relative flex items-center justify-center border-b border-gray-100 px-12 py-3 dark:border-gray-800">
          <h2 id="why-post-title" class="truncate text-lg font-bold">{{ t("postsFeed.why.title") }}</h2>
          <button type="button" class="icon-btn absolute end-2 top-1/2 -translate-y-1/2" :aria-label="t('postsFeed.why.close')" @click="emit('close')">
            <X class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <div class="space-y-3 p-4 text-sm">
          <p class="flex items-start gap-3">
            <Info class="mt-0.5 h-5 w-5 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
            <span dir="auto">{{ line }}</span>
          </p>
          <p v-if="mode" class="ps-8 text-gray-600 dark:text-gray-300">{{ t("postsFeed.why.mode", { mode: t(`homeFeed.modes.${mode}`) }) }}</p>
          <RouterLink to="/feeds/manage" class="btn-ghost w-full justify-center" @click="emit('close')">
            <Settings2 class="h-4 w-4" aria-hidden="true" /> {{ t("postsFeed.why.manage") }}
          </RouterLink>
        </div>
      </div>
    </div>
  </Teleport>
</template>
