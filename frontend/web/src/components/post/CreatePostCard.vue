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
// the home "create post" shortcut is left alone.
const props = withDefaults(defineProps<{ groupId?: string | null; groupName?: string }>(), {
  groupId: null,
  groupName: "",
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
    if (!requested || props.groupId) return;
    ui.composeRequested = false;
    openComposer();
  },
  { immediate: true },
);

const authorName = () => auth.profile?.display_name || auth.account?.email?.split("@")[0] || "?";
</script>

<template>
  <div class="card p-4">
    <!-- Behind the open (modal) dialog: hidden from assistive tech and from focus. -->
    <div :inert="open || undefined" :aria-hidden="open || undefined">
    <div class="flex items-center gap-3">
      <UserAvatar :name="authorName()" :media-id="auth.profile?.avatar_media_id" :size="40" />
      <button
        type="button"
        class="h-11 flex-1 rounded-full border border-transparent bg-gray-100 px-5 text-start text-sm text-gray-500 transition hover:border-brand-200 hover:bg-white dark:bg-gray-800/70 dark:text-gray-400 dark:hover:border-brand-900 dark:hover:bg-gray-800"
        aria-haspopup="dialog"
        data-testid="composer-open"
        @click="openComposer()"
      >
        {{ groupId ? t("groups.composer.placeholder") : t("feed.composerPlaceholder") }}
      </button>
    </div>

    <!-- Quick actions: each opens the composer in that mode. -->
    <div class="mt-3 grid grid-cols-3 gap-1 border-t border-gray-100 pt-2 dark:border-gray-800">
      <label class="btn-ghost cursor-pointer justify-center focus-within:ring-2 focus-within:ring-brand-400">
        <ImagePlus class="h-5 w-5 text-emerald-500" aria-hidden="true" />
        <span>{{ t("feed.photo") }}</span>
        <input type="file" :accept="IMAGE_ACCEPT" multiple class="sr-only" :aria-label="t('feed.addPhotos')" @change="onFiles" />
      </label>
      <button type="button" class="btn-ghost justify-center" aria-haspopup="dialog" @click="openComposer('feeling')">
        <Smile class="h-5 w-5 text-amber-500" aria-hidden="true" />
        <span class="truncate">{{ t("composer.feeling") }}</span>
      </button>
      <button type="button" class="btn-ghost justify-center" aria-haspopup="dialog" @click="openComposer('poll')">
        <BarChart3 class="h-5 w-5 text-accent-500" aria-hidden="true" />
        <span>{{ t("feed.poll") }}</span>
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
