<script setup lang="ts">
import { BarChart3, ImagePlus, Smile } from "lucide-vue-next";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import ComposerDialog from "@/components/post/ComposerDialog.vue";
import { IMAGE_ACCEPT } from "@/lib/heic";
import type { ComposerPost } from "@/services/composer";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";
import type { Post } from "@/types";

// The "What's on your mind?" card. Everything is written in ComposerDialog (one
// composer for text, photos, polls, tags, feeling, location, drafts and
// scheduling). With `groupId` the post goes into that group: no audience
// picker (the server forces the group audience), no drafts or scheduling, and
// the home "create post" shortcut is left alone. `listenShortcuts=false` leaves
// it alone too (the own-profile timeline: Home answers the shortcut).
const props = withDefaults(defineProps<{ groupId?: string | null; groupName?: string; listenShortcuts?: boolean }>(), {
  groupId: null,
  groupName: "",
  listenShortcuts: true,
});
const emit = defineEmits<{ created: [post: Post]; saved: [post: ComposerPost] }>();

const { t } = useI18n();
const auth = useAuthStore();
const ui = useUiStore();

type Start = "photo" | "poll" | "feeling" | "drafts" | null;
const open = ref(false);
const start = ref<Start>(null);
const files = ref<File[]>([]);

function openComposer(mode: Start = null, picked: File[] = []) {
  start.value = mode;
  files.value = picked;
  open.value = true;
}

function onFiles(e: Event) {
  const input = e.target as HTMLInputElement;
  const picked = Array.from(input.files ?? []);
  input.value = ""; // picking the same file again still fires `change`
  if (picked.length) openComposer("photo", picked);
}

// "Create post" shortcuts (main menu, sidebar, mobile bar) open the composer.
watch(
  () => ui.composeRequested,
  (requested) => {
    if (!requested || props.groupId || !props.listenShortcuts) return;
    ui.composeRequested = false;
    openComposer();
  },
  { immediate: true },
);

const authorName = () => auth.profile?.display_name || auth.account?.email?.split("@")[0] || "?";
</script>

<template>
  <div class="card p-3 sm:p-4">
    <!-- Behind the open (modal) dialog: hidden from assistive tech and from focus. -->
    <div :inert="open || undefined" :aria-hidden="open || undefined">
    <div class="flex items-center gap-1.5 sm:gap-2">
      <UserAvatar :name="authorName()" :media-id="auth.profile?.avatar_media_id" :size="40" />
      <button
        type="button"
        class="h-11 min-w-0 flex-1 truncate rounded-full border border-transparent bg-gray-100 px-5 text-start text-sm text-gray-600 transition hover:border-brand-200 hover:bg-white dark:bg-gray-800/70 dark:text-gray-400 dark:hover:border-brand-900 dark:hover:bg-gray-800"
        aria-haspopup="dialog"
        data-testid="composer-open"
        @click="openComposer()"
      >
        {{ groupId ? t("groups.composer.placeholder") : t("feed.composerPlaceholder") }}
      </button>

      <!-- Quick actions beside the field (reference layout): each opens the composer in that mode. -->
      <label
        class="inline-flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-full transition hover:bg-gray-100 focus-within:ring-2 focus-within:ring-brand-400 dark:hover:bg-gray-800"
        :title="t('feed.photo')"
        data-testid="composer-quick-photo"
      >
        <ImagePlus class="h-6 w-6 text-emerald-500" aria-hidden="true" />
        <input type="file" :accept="IMAGE_ACCEPT" multiple class="sr-only" :aria-label="t('feed.addPhotos')" @change="onFiles" />
      </label>
      <button
        type="button"
        class="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:hover:bg-gray-800"
        :aria-label="t('composer.feeling')"
        :title="t('composer.feeling')"
        aria-haspopup="dialog"
        @click="openComposer('feeling')"
      >
        <Smile class="h-6 w-6 text-amber-500" aria-hidden="true" />
      </button>
      <button
        type="button"
        class="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:hover:bg-gray-800"
        :aria-label="t('feed.poll')"
        :title="t('feed.poll')"
        aria-haspopup="dialog"
        @click="openComposer('poll')"
      >
        <BarChart3 class="h-6 w-6 text-accent-500" aria-hidden="true" />
      </button>
    </div>
    </div>

    <ComposerDialog
      v-if="open"
      :group-id="groupId"
      :group-name="groupName"
      :start="start"
      :files="files"
      @close="open = false"
      @published="(post) => emit('created', post)"
      @saved="(post) => emit('saved', post)"
    />
  </div>
</template>
