<script setup lang="ts">
import { Briefcase, Camera, ChevronDown, Eye, Images, ImageUp, Link2, MapPin, MessageCircle, Move, Pencil, Trash2 } from "lucide-vue-next";
import { computed, ref, toRefs } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AvatarCropDialog from "@/components/profile/AvatarCropDialog.vue";
import PhotoPickerDialog from "@/components/profile/PhotoPickerDialog.vue";
import FollowButton from "@/components/social/FollowButton.vue";
import FriendButton from "@/components/social/FriendButton.vue";
import PersonActionsMenu from "@/components/social/PersonActionsMenu.vue";
import { IMAGE_ACCEPT } from "@/lib/heic";
import { coverOffsetAfterDrag, coverPosition, normaliseCoverOffset } from "@/lib/photoFrame";
import { linkHost } from "@/lib/profileFormat";
import { useEscapeKey } from "@/lib/useEscapeKey";
import type { FriendsList, ProfileState, ProfileTab } from "@/lib/useProfile";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";

// Profile header in the reference layout: wide cover, overlapping avatar, name
// with follower/following and friend counts, friend avatars, the action row,
// then the tab row with the "..." menu at its end.
const props = defineProps<{ state: ProfileState }>();
const emit = defineEmits<{ edit: []; "open-photo": [src: string] }>();

const {
  profile,
  cover,
  avatar,
  displayName,
  userId,
  isSelf,
  relLoaded,
  relFailed,
  following,
  friendState,
  pendingRequestId,
  messaging,
  message,
  friendsCount,
  followersCount,
  followingCount,
  relFriendIds,
  mutual,
  tab,
  hasShop,
  savingPhoto,
} = toRefs(props.state);

const { t } = useI18n();
const presence = usePresenceStore();
const directory = useDirectoryStore();

// Marketplace joins only when the person has a shop this viewer may open.
const TABS = computed<ProfileTab[]>(() => [
  "posts",
  "about",
  "friends",
  "photos",
  // Reels (5.8): short vertical videos, next to the photos; the tab lists only what you may see.
  "reels",
  ...(hasShop.value ? (["marketplace"] as const) : []),
]);
// Phones show the first tabs and fold the rest into "More ▾" (the reference's overflow menu),
// so no tab is cut off at the edge of a sideways-scrolling row.
const PHONE_TABS = 3;
const overflowTabs = computed(() => TABS.value.slice(PHONE_TABS));
const moreOpen = ref(false);
useEscapeKey(moreOpen, () => (moreOpen.value = false));
function pickTab(tb: ProfileTab) {
  moreOpen.value = false;
  tab.value = tb;
}

function openFriends(list: FriendsList) {
  props.state.openTab("friends", list);
}

// Photo menus (owner only): upload / view / remove.
const photoMenu = ref<"" | "avatar" | "cover">("");
useEscapeKey(
  computed(() => !!photoMenu.value),
  () => (photoMenu.value = ""),
);
function pick(kind: "avatar" | "cover", e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  photoMenu.value = "";
  if (!file) return;
  // A new avatar is cropped first; a new cover is placed by dragging once it is up.
  if (kind === "avatar") crop.value = { file, src: null, mediaId: null };
  else void props.state.setPhoto("cover", file).then((ok) => ok && startReposition());
}

// ---- "Choose from your photos" (plan 08) ----
const picker = ref<"" | "avatar" | "cover">("");
function openPicker(kind: "avatar" | "cover") {
  photoMenu.value = "";
  picker.value = kind;
}
function picked(mediaId: string, url: string | null) {
  const kind = picker.value;
  picker.value = "";
  if (kind === "avatar") crop.value = { file: null, src: url, mediaId };
  else if (kind === "cover") void props.state.setPhoto("cover", { mediaId }).then((ok) => ok && startReposition());
}

// ---- avatar: crop and zoom before it is saved ----
const crop = ref<{ file: File | null; src: string | null; mediaId: string | null } | null>(null);
async function cropped(file: File) {
  if (await props.state.setPhoto("avatar", file)) crop.value = null;
}
async function useAsIs() {
  const c = crop.value;
  if (!c) return;
  let ok = false;
  if (c.file) ok = await props.state.setPhoto("avatar", c.file);
  else if (c.mediaId) ok = await props.state.setPhoto("avatar", { mediaId: c.mediaId });
  if (ok) crop.value = null;
}

// ---- cover: drag to reposition, then Save or Cancel ----
const coverFrame = ref<HTMLElement | null>(null);
const coverNatural = ref({ width: 0, height: 0 });
const repositioning = ref(false);
const draftOffset = ref(50);
const savedOffset = computed(() => normaliseCoverOffset(profile.value?.cover_offset_y));
const coverStyle = computed(() => ({ objectPosition: coverPosition(repositioning.value ? draftOffset.value : savedOffset.value) }));
function onCoverLoad(e: Event) {
  const el = e.target as HTMLImageElement;
  coverNatural.value = { width: el.naturalWidth, height: el.naturalHeight };
}
function startReposition() {
  photoMenu.value = "";
  if (!cover.value && !profile.value?.cover_media_id) return;
  draftOffset.value = savedOffset.value;
  repositioning.value = true;
  requestAnimationFrame(() => coverFrame.value?.focus());
}
function cancelReposition() {
  repositioning.value = false;
}
async function saveReposition() {
  if (await props.state.setCoverOffset(draftOffset.value)) repositioning.value = false;
}
useEscapeKey(repositioning, cancelReposition);
let coverDrag: { y: number; from: number } | null = null;
function onCoverDown(e: PointerEvent) {
  if (!repositioning.value) return;
  coverDrag = { y: e.clientY, from: draftOffset.value };
  (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
}
function onCoverMove(e: PointerEvent) {
  if (!coverDrag || !coverFrame.value) return;
  const r = coverFrame.value.getBoundingClientRect();
  draftOffset.value = coverOffsetAfterDrag(
    coverDrag.from,
    e.clientY - coverDrag.y,
    { width: r.width, height: r.height },
    coverNatural.value,
  );
}
function onCoverUp() {
  coverDrag = null;
}
function onCoverKey(e: KeyboardEvent) {
  if (!repositioning.value) return;
  const step = e.shiftKey ? 10 : 2;
  if (e.key === "ArrowUp") draftOffset.value = Math.max(0, draftOffset.value - step);
  else if (e.key === "ArrowDown") draftOffset.value = Math.min(100, draftOffset.value + step);
  else if (e.key === "Enter") void saveReposition();
  else return;
  e.preventDefault();
}
function removePhoto(kind: "avatar" | "cover") {
  photoMenu.value = "";
  void props.state.setPhoto(kind, null);
}
function view(src: string | null) {
  photoMenu.value = "";
  if (src) emit("open-photo", src);
}

const firstWork = computed(() => profile.value?.work?.find((w) => w.is_current) ?? profile.value?.work?.[0]);
const place = computed(() => [profile.value?.city, profile.value?.country].filter(Boolean).join(", "));
const firstLink = computed(() => profile.value?.links?.[0]);
const avatarsRow = computed(() => (isSelf.value || !mutual.value.length ? relFriendIds.value : mutual.value).slice(0, 8));

const menuItem =
  "flex w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 focus-within:bg-gray-100 dark:hover:bg-gray-800 dark:focus-within:bg-gray-800";
</script>

<template>
  <section class="card overflow-visible" data-testid="profile-hero">
    <!-- Cover -->
    <div class="relative">
      <div
        ref="coverFrame"
        class="relative h-44 overflow-hidden rounded-t-2xl bg-tara-gradient sm:h-64 lg:h-[22rem]"
        :class="repositioning ? 'cursor-grab touch-none select-none ring-4 ring-inset ring-brand-400 focus:outline-none active:cursor-grabbing' : ''"
        :tabindex="repositioning ? 0 : undefined"
        :role="repositioning ? 'slider' : undefined"
        :aria-label="repositioning ? t('profileTools.cover.dragHint') : undefined"
        :aria-valuenow="repositioning ? draftOffset : undefined"
        :aria-valuemin="repositioning ? 0 : undefined"
        :aria-valuemax="repositioning ? 100 : undefined"
        :aria-orientation="repositioning ? 'vertical' : undefined"
        :aria-describedby="repositioning ? 'cover-key-hint' : undefined"
        data-testid="cover-frame"
        :data-offset="repositioning ? draftOffset : savedOffset"
        @pointerdown="onCoverDown"
        @pointermove="onCoverMove"
        @pointerup="onCoverUp"
        @pointercancel="onCoverUp"
        @keydown="onCoverKey"
      >
        <div v-if="!cover" aria-hidden="true" class="absolute inset-0">
          <div class="absolute -top-24 end-10 h-72 w-72 rounded-full bg-white/20 blur-3xl" />
          <div class="absolute -bottom-24 start-0 h-72 w-96 rounded-full bg-ink/40 blur-3xl" />
        </div>
        <button
          v-if="cover && !isSelf"
          type="button"
          class="block h-full w-full"
          :aria-label="t('people.hero.openCover', { name: displayName })"
          @click="emit('open-photo', cover)"
        >
          <img :src="cover" class="h-full w-full object-cover" :style="coverStyle" :alt="t('profile.coverAlt', { name: displayName })" />
        </button>
        <img
          v-else-if="cover"
          :src="cover"
          class="pointer-events-none h-full w-full object-cover"
          :style="coverStyle"
          :alt="t('profile.coverAlt', { name: displayName })"
          draggable="false"
          data-testid="cover-image"
          @load="onCoverLoad"
        />
        <!-- Drag to reposition: the hint in the middle, Cancel / Save on top, as on the reference. -->
        <template v-if="repositioning">
          <span class="pointer-events-none absolute inset-0 m-auto flex h-10 w-fit items-center gap-2 rounded-full bg-gray-950/70 px-4 text-sm font-semibold text-white" aria-hidden="true">
            <Move class="h-4 w-4" aria-hidden="true" /> {{ t("profileTools.cover.dragHint") }}
          </span>
          <span id="cover-key-hint" class="sr-only">{{ t("profileTools.cover.keyHint") }}</span>
        </template>
      </div>
      <div
        v-if="repositioning"
        class="absolute inset-x-0 top-0 z-30 flex items-center justify-end gap-2 rounded-t-2xl bg-gray-950/60 p-3"
        data-testid="cover-reposition-bar"
      >
        <button type="button" class="btn bg-white/20 px-4 py-2 text-white hover:bg-white/30" data-testid="cover-reposition-cancel" @click="cancelReposition">
          {{ t("profileTools.cover.cancel") }}
        </button>
        <button type="button" class="btn-primary px-4 py-2" :disabled="savingPhoto === 'cover'" data-testid="cover-reposition-save" @click="saveReposition">
          {{ savingPhoto === "cover" ? t("profileTools.cover.saving") : t("profileTools.cover.save") }}
        </button>
      </div>

      <div v-if="isSelf && !repositioning" class="absolute bottom-3 end-3 sm:end-6">
        <button
          type="button"
          class="btn bg-white/95 px-3 py-2 text-gray-900 shadow hover:bg-white dark:bg-gray-900/90 dark:text-white dark:hover:bg-gray-900"
          aria-haspopup="menu"
          :aria-expanded="photoMenu === 'cover'"
          :aria-label="t('people.hero.editCover')"
          :disabled="savingPhoto === 'cover'"
          data-testid="edit-cover"
          @click="photoMenu = photoMenu === 'cover' ? '' : 'cover'"
        >
          <Camera class="h-4 w-4" />
          <span class="hidden sm:inline">{{ savingPhoto === "cover" ? t("profile.uploading") : t("people.hero.editCover") }}</span>
        </button>
        <template v-if="photoMenu === 'cover'">
          <div class="fixed inset-0 z-40" @click="photoMenu = ''" />
          <div class="popover absolute end-0 top-full z-50 mt-2 w-56 p-1.5" role="menu">
            <button v-if="cover" role="menuitem" :class="menuItem" @click="view(cover)"><Eye class="h-4 w-4" /> {{ t("people.hero.viewPhoto") }}</button>
            <button role="menuitem" :class="menuItem" data-testid="cover-choose" @click="openPicker('cover')">
              <Images class="h-4 w-4" /> {{ t("profileTools.cover.choose") }}
            </button>
            <label role="menuitem" :class="menuItem">
              <ImageUp class="h-4 w-4" /> {{ t("people.hero.uploadPhoto") }}
              <input type="file" :accept="IMAGE_ACCEPT" class="sr-only" data-testid="cover-input" @change="pick('cover', $event)" />
            </label>
            <button v-if="cover" role="menuitem" :class="menuItem" data-testid="cover-reposition" @click="startReposition">
              <Move class="h-4 w-4" /> {{ t("profileTools.cover.reposition") }}
            </button>
            <button v-if="cover" role="menuitem" :class="menuItem" class="text-red-600 dark:text-red-400" @click="removePhoto('cover')">
              <Trash2 class="h-4 w-4" /> {{ t("people.hero.removePhoto") }}
            </button>
          </div>
        </template>
      </div>
    </div>

    <!-- Identity row -->
    <div class="px-4 sm:px-8">
      <div class="flex flex-col items-center gap-3 lg:flex-row lg:items-end lg:gap-5">
        <!-- Avatar -->
        <div class="relative -mt-20 shrink-0 lg:-mt-[5.5rem]">
          <component
            :is="!isSelf && avatar ? 'button' : 'span'"
            :type="!isSelf && avatar ? 'button' : undefined"
            class="avatar-ring block rounded-full p-1 shadow-pop"
            :aria-label="!isSelf && avatar ? t('people.hero.openAvatar', { name: displayName }) : undefined"
            @click="!isSelf && avatar && emit('open-photo', avatar)"
          >
            <span class="block rounded-full border-4 border-white dark:border-gray-900">
              <UserAvatar :name="displayName" :media-id="profile?.avatar_media_id" :size="160" />
            </span>
          </component>
          <span
            v-if="userId && !isSelf && presence.isOnline(userId)"
            class="absolute bottom-4 end-4 h-6 w-6 rounded-full border-4 border-white bg-green-500 dark:border-gray-900"
            :title="t('presence.online')"
          />
          <div v-if="isSelf" class="absolute bottom-3 end-2">
            <button
              type="button"
              class="flex h-10 w-10 items-center justify-center rounded-full bg-gray-200 text-gray-900 shadow ring-2 ring-white transition hover:bg-gray-300 dark:bg-gray-800 dark:text-white dark:ring-gray-900 dark:hover:bg-gray-700"
              aria-haspopup="menu"
              :aria-expanded="photoMenu === 'avatar'"
              :aria-label="t('people.hero.updateAvatar')"
              :disabled="savingPhoto === 'avatar'"
              data-testid="edit-avatar"
              @click="photoMenu = photoMenu === 'avatar' ? '' : 'avatar'"
            >
              <Camera class="h-5 w-5" />
            </button>
            <template v-if="photoMenu === 'avatar'">
              <div class="fixed inset-0 z-40" @click="photoMenu = ''" />
              <div class="popover absolute start-0 top-full z-50 mt-2 w-56 p-1.5" role="menu">
                <button v-if="avatar" role="menuitem" :class="menuItem" @click="view(avatar)"><Eye class="h-4 w-4" /> {{ t("people.hero.viewPhoto") }}</button>
                <button role="menuitem" :class="menuItem" data-testid="avatar-choose" @click="openPicker('avatar')">
                  <Images class="h-4 w-4" /> {{ t("profileTools.avatar.choose") }}
                </button>
                <label role="menuitem" :class="menuItem">
                  <ImageUp class="h-4 w-4" /> {{ t("people.hero.uploadPhoto") }}
                  <input type="file" :accept="IMAGE_ACCEPT" class="sr-only" data-testid="avatar-input" @change="pick('avatar', $event)" />
                </label>
                <button v-if="avatar" role="menuitem" :class="menuItem" class="text-red-600 dark:text-red-400" @click="removePhoto('avatar')">
                  <Trash2 class="h-4 w-4" /> {{ t("people.hero.removePhoto") }}
                </button>
              </div>
            </template>
          </div>
        </div>

        <!-- Name, counts, friend avatars -->
        <div class="min-w-0 flex-1 pb-1 text-center lg:pb-4 lg:text-start">
          <h1 class="text-[1.75rem] font-extrabold leading-tight sm:text-[2rem]"><bdi>{{ displayName }}</bdi></h1>
          <!-- The handle is LTR text inside the page's direction: isolate it, don't flip the line's alignment. -->
          <p v-if="profile?.handle" class="text-sm text-gray-500 dark:text-gray-400" data-testid="hero-handle"><bdi dir="ltr">@{{ profile.handle }}</bdi></p>

          <p class="mt-1 flex flex-wrap items-center justify-center gap-x-1.5 text-[15px] font-semibold text-gray-600 dark:text-gray-300 lg:justify-start">
            <button v-if="friendsCount !== null" type="button" class="hover:underline" data-testid="hero-friends" @click="openFriends('all')">
              {{ t("people.hero.friends", friendsCount) }}
            </button>
            <span v-if="friendsCount !== null && followersCount !== null" aria-hidden="true">•</span>
            <button v-if="followersCount !== null" type="button" class="hover:underline" data-testid="hero-followers" @click="openFriends('followers')">
              {{ t("people.hero.followers", followersCount) }}
            </button>
            <span v-if="followersCount !== null && followingCount !== null" aria-hidden="true">•</span>
            <button v-if="followingCount !== null" type="button" class="hover:underline" data-testid="hero-following" @click="openFriends('following')">
              {{ t("people.hero.following", followingCount) }}
            </button>
          </p>

          <button
            v-if="avatarsRow.length"
            type="button"
            class="mt-2 inline-flex items-center gap-2"
            :aria-label="!isSelf && mutual.length ? t('people.hero.mutual', mutual.length) : t('people.hero.friends', relFriendIds.length)"
            data-testid="hero-avatars"
            @click="openFriends(!isSelf && mutual.length ? 'mutual' : 'all')"
          >
            <span class="flex -space-x-2 rtl:space-x-reverse">
              <UserAvatar
                v-for="m in avatarsRow"
                :key="m"
                :name="directory.label(m)"
                :media-id="directory.avatarOf(m)"
                :size="32"
                class="ring-2 ring-white dark:ring-gray-900"
              />
            </span>
            <span v-if="!isSelf && mutual.length" class="text-sm text-gray-500 hover:underline dark:text-gray-400">{{ t("people.hero.mutual", mutual.length) }}</span>
          </button>

          <p
            v-if="firstWork || place"
            class="mt-2 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-sm text-gray-700 dark:text-gray-200 lg:justify-start"
          >
            <span v-if="firstWork" class="inline-flex items-center gap-1" dir="auto">
              <Briefcase class="h-4 w-4 text-gray-500" />{{ firstWork.title || firstWork.company }}
            </span>
            <span v-if="firstWork && place" aria-hidden="true">·</span>
            <span v-if="place" class="inline-flex items-center gap-1" dir="auto"><MapPin class="h-4 w-4 text-gray-500" />{{ place }}</span>
          </p>
        </div>

        <!-- Actions + short bio -->
        <div class="flex w-full flex-col items-center gap-3 pb-4 lg:w-auto lg:items-end">
          <div class="flex flex-wrap items-center justify-center gap-2 lg:justify-end">
            <button v-if="isSelf" class="btn-soft" @click="emit('edit')">
              <Pencil class="h-4 w-4" /> {{ t("profile.editProfile") }}
            </button>
            <template v-else-if="userId && relLoaded">
              <!-- Friends follow by default: Unfollow lives in the Friends menu, as on the reference. -->
              <template v-if="!relFailed && friendState !== 'friends'">
                <FollowButton :user-id="userId" :following="following" @change="state.onFollowChange" />
              </template>
              <button class="btn-primary" :disabled="messaging" @click="message">
                <MessageCircle class="h-4 w-4" /> {{ t("profile.message") }}
              </button>
              <FriendButton
                v-if="!relFailed"
                :user-id="userId"
                :state="friendState"
                :request-id="pendingRequestId"
                :name="displayName"
                :following="following"
                @change="state.onFriendChange"
                @follow-change="state.onFollowChange"
              />
            </template>
          </div>
          <div v-if="profile?.bio || firstLink" class="hidden max-w-sm text-end text-sm lg:block">
            <p v-if="profile?.bio" class="line-clamp-3 whitespace-pre-line text-gray-700 dark:text-gray-200" dir="auto">{{ profile.bio }}</p>
            <a
              v-if="firstLink"
              :href="firstLink.url"
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex items-center gap-1 font-medium text-brand-600 hover:underline dark:text-brand-300"
              dir="ltr"
            >
              <Link2 class="h-3.5 w-3.5" />{{ linkHost(firstLink.url) }}
            </a>
          </div>
        </div>
      </div>

      <!-- Profile completion (self) -->
      <div
        v-if="isSelf && typeof profile?.completion_pct === 'number' && profile.completion_pct < 100"
        class="mb-3 rounded-xl bg-brand-50 p-3 dark:bg-brand-950/30"
      >
        <div class="flex items-center justify-between text-xs font-medium text-brand-700 dark:text-brand-300">
          <span>{{ t("profile.completion", { pct: profile.completion_pct }) }}</span>
          <button class="font-semibold underline" @click="emit('edit')">{{ t("profile.editProfile") }}</button>
        </div>
        <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-brand-100 dark:bg-brand-900/50">
          <div class="h-full rounded-full bg-brand-600" :style="{ width: profile.completion_pct + '%' }" />
        </div>
        <p class="mt-1 text-[11px] text-brand-700/80 dark:text-brand-300/80">{{ t("profile.completeHint") }}</p>
      </div>

      <!-- Tabs row + "..." -->
      <div class="flex items-center gap-2 border-t border-gray-200 dark:border-gray-800">
        <nav class="-mb-px flex min-w-0 items-center sm:flex-1" :aria-label="t('people.hero.tabs')" role="tablist">
          <button
            v-for="(tb, i) in TABS"
            :key="tb"
            type="button"
            role="tab"
            :aria-selected="tab === tb"
            :data-testid="`profile-tab-${tb}`"
            class="relative whitespace-nowrap px-3 py-4 text-[15px] font-semibold transition sm:px-4"
            :class="[
              i >= PHONE_TABS ? 'hidden sm:block' : '',
              tab === tb
                ? 'text-brand-600 after:absolute after:inset-x-1 after:bottom-0 after:h-[3px] after:rounded-full after:bg-brand-600 dark:text-brand-300 dark:after:bg-brand-400'
                : 'rounded-lg text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800',
            ]"
            @click="tab = tb"
          >
            {{ t(`people.tabs.${tb}`) }}
          </button>
        </nav>
        <!-- Outside the tablist: it is a menu button, not a tab. -->
        <div class="relative -mb-px flex-1 sm:hidden">
          <button
            type="button"
            class="relative inline-flex items-center gap-1 whitespace-nowrap px-3 py-4 text-[15px] font-semibold transition"
            :class="
              overflowTabs.includes(tab)
                ? 'text-brand-600 after:absolute after:inset-x-1 after:bottom-0 after:h-[3px] after:rounded-full after:bg-brand-600 dark:text-brand-300 dark:after:bg-brand-400'
                : 'rounded-lg text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'
            "
            aria-haspopup="menu"
            :aria-expanded="moreOpen"
            data-testid="profile-tab-more"
            @click="moreOpen = !moreOpen"
          >
            {{ overflowTabs.includes(tab) ? t(`people.tabs.${tab}`) : t("people.tabs.more") }}
            <ChevronDown class="h-4 w-4" aria-hidden="true" />
          </button>
          <template v-if="moreOpen">
            <div class="fixed inset-0 z-40" @click="moreOpen = false" />
            <div class="popover absolute start-0 top-full z-50 mt-1 w-44 p-1.5" role="menu">
              <button
                v-for="tb in overflowTabs"
                :key="tb"
                type="button"
                role="menuitem"
                :class="menuItem"
                :data-testid="`profile-tab-more-${tb}`"
                @click="pickTab(tb)"
              >
                {{ t(`people.tabs.${tb}`) }}
              </button>
            </div>
          </template>
        </div>
        <PersonActionsMenu
          v-if="userId"
          :user-id="userId"
          :name="displayName"
          :self="isSelf"
          :is-friend="friendState === 'friends'"
          :hide-creator="!isSelf"
          copy-link
          privacy-link
          button-class="btn-soft px-3 py-2"
          @unfriended="state.onFriendChange('none')"
          @blocked="(on) => on && state.onFriendChange('none')"
        />
      </div>
    </div>

    <PhotoPickerDialog
      v-if="picker && userId"
      :account-id="userId"
      :title="picker === 'cover' ? t('profileTools.cover.choose') : t('profileTools.avatar.choose')"
      @close="picker = ''"
      @pick="picked"
    />
    <AvatarCropDialog
      v-if="crop"
      :file="crop.file"
      :src="crop.src"
      :busy="savingPhoto === 'avatar'"
      @close="crop = null"
      @cropped="cropped"
      @as-is="useAsIs"
    />
  </section>
</template>
