<script setup lang="ts">
import { Info, Settings2, X } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { itemKey, servedToken } from "@/lib/signals";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { type FeedReason, feedService, isFeedMode, type WhyFactor } from "@/services/feed";
import { useDirectoryStore } from "@/stores/directory";

// "Why am I seeing this post?" (WP 4.8). The feed's own reason for the item shows
// at once; the server's explanation (`/feed/why/post/<id>/`, which answers only
// for an item it served to this viewer) then replaces it with the factors that
// applied. Nothing is guessed: if the server does not answer, the reason stays.
const props = withDefaults(
  defineProps<{
    reason: FeedReason;
    name: string;
    page?: boolean;
    mode?: string | null;
    postId?: string | null;
    authorId?: string | null;
  }>(),
  { page: false, mode: null, postId: null, authorId: null },
);
const emit = defineEmits<{ close: [] }>();

const { t } = useI18n();
const directory = useDirectoryStore();
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
useEscapeKey(ref(true), () => emit("close"));

const factors = ref<WhyFactor[] | null>(null);
const servedMode = ref<string | null>(null);

const fallback = computed(() => {
  if (props.reason === "self") return t("postsFeed.why.self");
  if (props.reason === "friend") return t("postsFeed.why.friend", { name: props.name });
  return t(props.page ? "postsFeed.why.page" : "postsFeed.why.follow", { name: props.name });
});

function nameOf(f: WhyFactor): string {
  if (!f.author_id || f.author_id === props.authorId) return props.name;
  return directory.label(f.author_id);
}

// One sentence per factor the server sent; codes this client does not know are skipped.
function sentence(f: WhyFactor): string | null {
  switch (f.code) {
    case "self":
      return t("postsFeed.why.self");
    case "friend":
      return t("postsFeed.why.friend", { name: nameOf(f) });
    case "follow":
      return t("postsFeed.why.follow", { name: nameOf(f) });
    case "page_follow":
      return t("postsFeed.why.page", { name: nameOf(f) });
    case "group_member":
      return t("postsFeed.why.groupMember");
    case "public_pool":
      return t("postsFeed.why.publicPool");
    case "favorite":
      return t("postsFeed.why.favorite", { name: nameOf(f) });
    case "interacted_author":
      return t("postsFeed.why.interacted", { name: nameOf(f) });
    case "shared_groups":
      return t("postsFeed.why.sharedGroups", { name: nameOf(f) });
    case "conversation":
      return t("postsFeed.why.conversation", { name: nameOf(f) });
    case "demoted_feedback":
      return t("postsFeed.why.demoted");
    case "rec_topic":
      return f.topic ? t("postsFeed.why.topic", { topic: f.topic }) : null;
    case "rec_topic_sensitive":
      return t("postsFeed.why.topicSensitive");
    default:
      return null;
  }
}

const lines = computed(() => {
  const fromServer = (factors.value ?? []).map(sentence).filter((s): s is string => !!s);
  return fromServer.length ? fromServer : [fallback.value];
});
const shownMode = computed(() => {
  const m = servedMode.value ?? props.mode;
  return isFeedMode(m) ? m : null;
});

onMounted(async () => {
  if (!props.postId) return;
  try {
    const why = await feedService.why(props.postId, servedToken(itemKey("post", props.postId)));
    factors.value = why.factors;
    servedMode.value = why.mode;
  } catch {
    // Not served here (404) or offline: the feed's own reason stays.
  }
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
          <ul class="space-y-2" data-testid="why-factors">
            <li v-for="(line, i) in lines" :key="i" class="flex items-start gap-3">
              <Info class="mt-0.5 h-5 w-5 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
              <span dir="auto">{{ line }}</span>
            </li>
          </ul>
          <p v-if="shownMode" class="ps-8 text-gray-600 dark:text-gray-300">{{ t("postsFeed.why.mode", { mode: t(`homeFeed.modes.${shownMode}`) }) }}</p>
          <RouterLink to="/feeds/manage" class="btn-ghost w-full justify-center" @click="emit('close')">
            <Settings2 class="h-4 w-4" aria-hidden="true" /> {{ t("postsFeed.why.manage") }}
          </RouterLink>
        </div>
      </div>
    </div>
  </Teleport>
</template>
