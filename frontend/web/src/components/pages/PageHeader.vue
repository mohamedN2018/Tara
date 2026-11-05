<script setup lang="ts">
import { Bookmark, BookmarkCheck, Camera, Flag, ImageUp, Link2, MoreHorizontal, PenSquare, Settings2, Trash2, UserMinus } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import PageMessageButton from "@/components/chat/PageMessageButton.vue";
import UserAvatar from "@/components/common/UserAvatar.vue";
import { IMAGE_ACCEPT } from "@/lib/heic";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useMediaUrl } from "@/lib/useMediaUrl";
import { canEditPage, canPostAs, type Page } from "@/services/pages";

import PageFollowButton from "./PageFollowButton.vue";

export type PageTab = "posts" | "about" | "reels" | "team";

// The page's public header in the reference layout: wide cover, big round
// avatar overlapping it, name, follower count and category, then the action
// row (Follow, or Create post / Edit page for the team) and the tab row with
// the "..." menu (copy link, save, unfollow, report). Every action is checked
// again on the server.
const props = defineProps<{ page: Page; tab: PageTab; saved: boolean | null; busyPhoto: "" | "avatar" | "cover" }>();
const emit = defineEmits<{
  "update:tab": [tab: PageTab];
  follow: [following: boolean];
  edit: [];
  compose: [];
  photo: [kind: "avatar" | "cover", file: File | null];
  copy: [];
  save: [];
  report: [];
  unfollow: [];
}>();

const { t } = useI18n();
const cover = useMediaUrl(() => props.page.cover_media_id);
const isTeam = computed(() => !!props.page.my_role);
const editor = computed(() => canEditPage(props.page));
const tabs = computed<PageTab[]>(() => (isTeam.value ? ["posts", "about", "reels", "team"] : ["posts", "about", "reels"]));

const menuOpen = ref(false);
const photoMenu = ref<"" | "avatar" | "cover">("");
useEscapeKey(menuOpen, () => (menuOpen.value = false));
useEscapeKey(
  computed(() => !!photoMenu.value),
  () => (photoMenu.value = ""),
);

function pick(kind: "avatar" | "cover", e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  photoMenu.value = "";
  if (file) emit("photo", kind, file);
}
function act(name: "copy" | "save" | "report" | "unfollow") {
  menuOpen.value = false;
  if (name === "copy") emit("copy");
  else if (name === "save") emit("save");
  else if (name === "report") emit("report");
  else emit("unfollow");
}
const menuItem = "nav-item w-full";
</script>

<template>
  <header class="card overflow-hidden rounded-t-none sm:rounded-t-2xl" aria-labelledby="page-title" data-testid="page-header">
    <!-- Cover -->
    <div class="relative mx-auto aspect-[2.7/1] max-h-[25rem] w-full bg-tara-gradient sm:aspect-[3/1]">
      <img v-if="cover" :src="cover" class="h-full w-full object-cover" :alt="t('pageHub.header.coverAlt', { name: page.name })" />
      <div v-if="editor" class="absolute bottom-3 end-3">
        <button
          type="button"
          class="btn-soft bg-white/90 text-gray-900 shadow dark:bg-gray-900/90 dark:text-white"
          aria-haspopup="menu"
          :aria-expanded="photoMenu === 'cover'"
          :disabled="busyPhoto === 'cover'"
          data-testid="page-edit-cover"
          @click="photoMenu = photoMenu === 'cover' ? '' : 'cover'"
        >
          <Camera class="h-4 w-4" aria-hidden="true" />
          <span class="hidden sm:inline">{{ busyPhoto === "cover" ? t("pageHub.header.uploading") : t("pageHub.header.changeCover") }}</span>
          <span class="sr-only sm:hidden">{{ t("pageHub.header.changeCover") }}</span>
        </button>
        <template v-if="photoMenu === 'cover'">
          <div class="fixed inset-0 z-40" @click="photoMenu = ''" />
          <div class="popover absolute bottom-full end-0 z-50 mb-1 w-56 p-1" role="menu">
            <label role="menuitem" :class="menuItem" class="cursor-pointer">
              <ImageUp class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.header.changeCover") }}
              <input type="file" :accept="IMAGE_ACCEPT" class="sr-only" data-testid="page-cover-input" @change="pick('cover', $event)" />
            </label>
            <button v-if="page.cover_media_id" type="button" role="menuitem" :class="menuItem" class="text-red-600 dark:text-red-400" @click="photoMenu = ''; emit('photo', 'cover', null)">
              <Trash2 class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.header.removeCover") }}
            </button>
          </div>
        </template>
      </div>
    </div>

    <!-- Identity + actions -->
    <div class="px-4 sm:px-8">
      <div class="flex flex-col items-center gap-3 sm:flex-row sm:items-end sm:gap-5">
        <div class="relative -mt-16 shrink-0 sm:-mt-10">
          <span class="block rounded-full border-4 border-white bg-white dark:border-gray-900 dark:bg-gray-900">
            <span class="hidden sm:block"><UserAvatar :name="page.name" :media-id="page.avatar_media_id" :size="168" /></span>
            <span class="block sm:hidden"><UserAvatar :name="page.name" :media-id="page.avatar_media_id" :size="128" /></span>
          </span>
          <label
            v-if="editor"
            class="absolute bottom-2 end-2 flex h-9 w-9 cursor-pointer items-center justify-center rounded-full bg-gray-200 text-gray-900 shadow hover:bg-gray-300 dark:bg-gray-700 dark:text-white dark:hover:bg-gray-600"
            :title="t('pageHub.header.changeAvatar')"
            data-testid="page-edit-avatar"
          >
            <Camera class="h-5 w-5" aria-hidden="true" />
            <span class="sr-only">{{ busyPhoto === "avatar" ? t("pageHub.header.uploading") : t("pageHub.header.changeAvatar") }}</span>
            <input type="file" :accept="IMAGE_ACCEPT" class="sr-only" :disabled="busyPhoto === 'avatar'" data-testid="page-avatar-input" @change="pick('avatar', $event)" />
          </label>
        </div>

        <div class="min-w-0 flex-1 pb-1 text-center sm:pb-4 sm:text-start">
          <h1 id="page-title" class="break-words text-2xl font-extrabold leading-tight sm:text-3xl" data-testid="page-name"><bdi>{{ page.name }}</bdi></h1>
          <p class="mt-1 text-sm font-semibold text-gray-500 dark:text-gray-400">
            <span v-if="page.followers_count !== null" data-testid="page-followers">
              {{ t("pageHub.card.followers", { count: page.followers_count }, page.followers_count) }}
            </span>
            <template v-if="page.followers_count !== null && page.category"> · </template>
            <span v-if="page.category" dir="auto">{{ page.category }}</span>
          </p>
          <p class="text-xs text-gray-500 dark:text-gray-400"><span dir="ltr">@{{ page.handle }}</span></p>
          <p v-if="page.status !== 'published'" class="mt-1 text-xs font-semibold text-amber-600 dark:text-amber-400">{{ t(`pages.status.${page.status}`) }}</p>
        </div>

        <div class="flex w-full flex-wrap items-center justify-center gap-2 pb-4 sm:w-auto sm:justify-end">
          <button v-if="canPostAs(page)" type="button" class="btn-primary" data-testid="page-create-post" @click="emit('compose')">
            <PenSquare class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.card.createPost") }}
          </button>
          <button v-if="editor" type="button" class="btn-soft" data-testid="page-edit" @click="emit('edit')">
            <Settings2 class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.header.editPage") }}
          </button>
          <PageMessageButton :page="page" />
          <PageFollowButton
            v-if="!isTeam && page.viewer_following !== null"
            :page-id="page.id"
            :name="page.name"
            :following="page.viewer_following"
            @changed="emit('follow', $event)"
          />
        </div>
      </div>

      <!-- Tabs + more -->
      <div class="flex items-center gap-2 border-t border-gray-200 dark:border-gray-800">
        <nav class="flex min-w-0 flex-1 gap-1 overflow-x-auto" role="tablist" :aria-label="t('pageHub.tabs.label')">
          <button
            v-for="x in tabs"
            :id="`page-tab-${x}`"
            :key="x"
            type="button"
            role="tab"
            :aria-selected="tab === x"
            aria-controls="page-panel"
            class="relative shrink-0 px-4 py-4 text-sm font-semibold transition"
            :class="tab === x ? 'text-brand-600 dark:text-brand-300' : 'rounded-lg text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'"
            :data-testid="`page-tab-${x}`"
            @click="emit('update:tab', x)"
          >
            {{ t(`pageHub.tabs.${x}`) }}
            <span v-if="tab === x" class="absolute inset-x-2 bottom-0 h-[3px] rounded-full bg-brand-600 dark:bg-brand-300" aria-hidden="true" />
          </button>
        </nav>
        <div class="relative shrink-0">
          <button
            type="button"
            class="btn-soft px-3"
            :aria-label="t('pageHub.header.more')"
            aria-haspopup="menu"
            :aria-expanded="menuOpen"
            data-testid="page-more"
            @click="menuOpen = !menuOpen"
          >
            <MoreHorizontal class="h-5 w-5" aria-hidden="true" />
          </button>
          <template v-if="menuOpen">
            <div class="fixed inset-0 z-40" @click="menuOpen = false" />
            <div class="popover absolute end-0 z-50 mt-1 w-60 p-1" role="menu">
              <button type="button" role="menuitem" :class="menuItem" @click="act('copy')">
                <Link2 class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.header.copyLink") }}
              </button>
              <button v-if="saved !== null" type="button" role="menuitem" :class="menuItem" data-testid="page-save" @click="act('save')">
                <component :is="saved ? BookmarkCheck : Bookmark" class="h-4 w-4" aria-hidden="true" />
                {{ saved ? t("pageHub.header.unsave") : t("pageHub.header.save") }}
              </button>
              <button v-if="!isTeam && page.viewer_following" type="button" role="menuitem" :class="menuItem" @click="act('unfollow')">
                <UserMinus class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.header.unfollow") }}
              </button>
              <button v-if="!isTeam" type="button" role="menuitem" :class="menuItem" data-testid="page-report" @click="act('report')">
                <Flag class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.header.report") }}
              </button>
            </div>
          </template>
        </div>
      </div>
    </div>
  </header>
</template>
