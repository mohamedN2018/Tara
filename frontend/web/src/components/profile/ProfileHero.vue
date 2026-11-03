<script setup lang="ts">
import { Ban, CalendarDays, Link2, MapPin, MessageCircle, MoreHorizontal } from "lucide-vue-next";
import { ref, toRefs } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import FollowButton from "@/components/social/FollowButton.vue";
import FriendButton from "@/components/social/FriendButton.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import type { ProfileState } from "@/lib/useProfile";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";
import { useToastStore } from "@/stores/toasts";

const props = defineProps<{ state: ProfileState }>();
defineEmits<{ edit: [] }>();

const {
  profile,
  cover,
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
  blocked,
  blocking,
  toggleBlock,
  postsLabel,
  friendsCount,
  followersCount,
  mutual,
  joinedText,
  tab,
} = toRefs(props.state);

const { t } = useI18n();
const presence = usePresenceStore();
const directory = useDirectoryStore();
const toasts = useToastStore();

const menuOpen = ref(false);
useEscapeKey(menuOpen, () => (menuOpen.value = false));
const copied = ref(false);
async function copyLink() {
  menuOpen.value = false;
  try {
    await navigator.clipboard.writeText(window.location.href);
    copied.value = true;
    window.setTimeout(() => (copied.value = false), 2000);
  } catch {
    toasts.push({ text: t("errors.copyFailed"), icon: "error" });
  }
}

function onToggleBlock() {
  menuOpen.value = false;
  void toggleBlock.value();
}
</script>

<template>
  <div class="card overflow-hidden">
    <div class="relative h-48 bg-gradient-to-r from-brand-100 to-brand-50 dark:from-brand-900/40 dark:to-gray-800 sm:h-64">
      <img v-if="cover" :src="cover" class="h-full w-full object-cover" :alt="t('profile.coverAlt', { name: displayName })" />
    </div>

    <div class="px-4 pb-4 sm:px-6">
      <div class="-mt-16 flex flex-col gap-3 sm:-mt-20 sm:flex-row sm:items-end sm:justify-between">
        <span class="relative inline-block w-fit">
          <span class="block rounded-full border-4 border-white dark:border-gray-900">
            <UserAvatar :name="displayName" :media-id="profile?.avatar_media_id" :size="128" />
          </span>
          <span
            v-if="userId && presence.isOnline(userId)"
            class="absolute end-3 bottom-3 h-5 w-5 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
            :title="t('presence.online')"
          />
        </span>

        <div class="flex flex-wrap items-center gap-2 pb-1">
          <button v-if="isSelf" class="btn-primary" @click="$emit('edit')">
            {{ t("profile.editProfile") }}
          </button>
          <template v-else-if="userId && relLoaded">
            <template v-if="!relFailed">
              <FollowButton :user-id="userId" :following="following" />
              <FriendButton :user-id="userId" :state="friendState" :request-id="pendingRequestId" />
            </template>
            <button class="btn-soft" :disabled="messaging" @click="message">
              <MessageCircle class="h-4 w-4" /> {{ t("profile.message") }}
            </button>
          </template>

          <div class="relative">
            <button class="btn-ghost px-2" :aria-label="t('profile.more')" @click="menuOpen = !menuOpen">
              <MoreHorizontal class="h-5 w-5" />
            </button>
            <template v-if="menuOpen">
              <div class="fixed inset-0 z-40" @click="menuOpen = false" />
              <div class="card absolute end-0 z-50 mt-2 w-52 p-1.5" role="menu">
                <button class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800" @click="copyLink">
                  <Link2 class="h-4 w-4" /> {{ t("profile.copyLink") }}
                </button>
                <button
                  v-if="!isSelf && userId"
                  class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm text-red-600 transition hover:bg-red-50 disabled:opacity-60 dark:hover:bg-red-950/40"
                  :disabled="blocking"
                  @click="onToggleBlock"
                >
                  <Ban class="h-4 w-4" /> {{ blocked ? t("profile.unblock") : t("profile.block") }}
                </button>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- Identity -->
      <div class="mt-3">
        <h1 class="text-2xl font-bold" dir="auto">{{ displayName }}</h1>
        <p v-if="profile?.intro" class="mt-0.5 text-sm text-gray-600 dark:text-gray-300" dir="auto">{{ profile.intro }}</p>
        <p v-if="profile?.handle" class="text-sm text-gray-500" dir="ltr">@{{ profile.handle }}</p>

        <div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-500">
          <span class="font-medium text-gray-700 dark:text-gray-200">{{ postsLabel }}</span>
          <button
            v-if="friendsCount !== null"
            class="hover:text-brand-600 hover:underline"
            @click="tab = 'friends'"
          >
            {{ t("profile.friendsCount", friendsCount) }}
          </button>
          <RouterLink
            v-if="followersCount !== null && isSelf"
            to="/connections"
            class="hover:text-brand-600 hover:underline"
          >
            {{ t("profile.followersCount", followersCount) }}
          </RouterLink>
          <span v-else-if="followersCount !== null">{{ t("profile.followersCount", followersCount) }}</span>
          <span v-if="profile?.city || profile?.country" class="inline-flex items-center gap-1">
            <MapPin class="h-3.5 w-3.5" />
            {{ [profile?.city, profile?.country].filter(Boolean).join(", ") }}
          </span>
          <span v-if="profile?.created_at" class="inline-flex items-center gap-1">
            <CalendarDays class="h-3.5 w-3.5" /> {{ joinedText(profile.created_at) }}
          </span>
        </div>

        <!-- Mutual friends (others) -->
        <div v-if="!isSelf && mutual.length" class="mt-2 flex items-center gap-2 text-sm text-gray-500">
          <span class="flex -space-x-2 rtl:space-x-reverse">
            <UserAvatar v-for="m in mutual.slice(0, 3)" :key="m" :name="directory.label(m)" :media-id="directory.avatarOf(m)" :size="22" class="ring-2 ring-white dark:ring-gray-900" />
          </span>
          {{ t("profile.mutual", mutual.length) }}
        </div>

        <!-- Profile completion (self) -->
        <div
          v-if="isSelf && typeof profile?.completion_pct === 'number' && profile.completion_pct < 100"
          class="mt-3 rounded-xl bg-brand-50 p-3 dark:bg-brand-950/30"
        >
          <div class="flex items-center justify-between text-xs font-medium text-brand-700 dark:text-brand-300">
            <span>{{ t("profile.completion", { pct: profile.completion_pct }) }}</span>
            <button class="font-semibold underline" @click="$emit('edit')">{{ t("profile.editProfile") }}</button>
          </div>
          <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-brand-100 dark:bg-brand-900/50">
            <div class="h-full rounded-full bg-brand-600" :style="{ width: profile.completion_pct + '%' }" />
          </div>
          <p class="mt-1 text-[11px] text-brand-700/70 dark:text-brand-300/70">{{ t("profile.completeHint") }}</p>
        </div>

        <p v-if="copied" class="mt-2 text-xs font-medium text-green-600">{{ t("profile.linkCopied") }}</p>
      </div>

      <!-- Tabs -->
      <div class="mt-4 flex gap-1 overflow-x-auto border-t border-gray-100 pt-2 dark:border-gray-800">
        <button
          v-for="tb in (['posts', 'photos', 'friends'] as const)"
          :key="tb"
          class="whitespace-nowrap rounded-lg px-4 py-2 text-sm font-semibold transition"
          :class="tab === tb ? 'bg-brand-50 text-brand-600 dark:bg-brand-950/40' : 'text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800'"
          @click="tab = tb"
        >
          {{ tb === "posts" ? t("profile.posts") : tb === "photos" ? t("profile.photos") : t("profile.friends") }}
        </button>
      </div>
    </div>
  </div>
</template>
