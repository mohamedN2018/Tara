<script setup lang="ts">
import {
  Ban,
  Briefcase,
  CalendarDays,
  GraduationCap,
  Link2,
  LinkIcon,
  MapPin,
  MessageCircle,
  MoreHorizontal,
  X,
} from "lucide-vue-next";
import { computed, defineAsyncComponent, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import PostCard from "@/components/post/PostCard.vue";
import FollowButton from "@/components/social/FollowButton.vue";
import FriendButton from "@/components/social/FriendButton.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useMediaUrl, useMediaUrls } from "@/lib/useMediaUrl";
import { chatService } from "@/services/chat";
import { type FriendRequest, type FriendState, graphService } from "@/services/graph";
import { postService } from "@/services/post";
import { profileService } from "@/services/profile";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";
import type { Post, Profile } from "@/types";

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const presence = usePresenceStore();
const directory = useDirectoryStore();

// Loaded only when the editor is opened (keeps the profile bundle small).
const EditProfileModal = defineAsyncComponent(
  () => import("@/components/profile/EditProfileModal.vue"),
);

const profile = ref<Profile | null>(null);
const posts = ref<Post[]>([]);
const loading = ref(true);
const loadingPosts = ref(false);
const error = ref(false);
const tab = ref<"posts" | "photos" | "friends">("posts");

const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loadingMore = ref(false);

// Relationship + counts (real data from the graph service).
const following = ref(false);
const friendState = ref<FriendState>("none");
const pendingRequestId = ref<string | undefined>(undefined);
const relLoaded = ref(false);
const followersCount = ref<number | null>(null);
const friendsCount = ref<number | null>(null);
const mutual = ref<string[]>([]);
const relFriendIds = ref<string[]>([]);

const handleParam = computed(() => (route.params.handle as string) || "");
const idParam = computed(() => (route.params.id as string) || (route.query.uid as string) || "");

const isSelfRoute = computed(() => {
  if (handleParam.value) return !!auth.profile && auth.profile.handle === handleParam.value;
  if (idParam.value) return auth.account?.id === idParam.value;
  return false;
});

const cover = useMediaUrl(() => profile.value?.cover_media_id);
const userId = computed(() => {
  // Posts are keyed by account_id (author_id), NOT the profile record's PK.
  if (isSelfRoute.value || profile.value?.is_self) {
    return auth.account?.id ?? profile.value?.account_id ?? null;
  }
  return profile.value?.user_id || profile.value?.account_id || idParam.value || null;
});
const isSelf = computed(() => profile.value?.is_self ?? isSelfRoute.value);
const nameHint = computed(() => (route.query.name as string) || "");
const displayName = computed(
  () =>
    profile.value?.display_name ||
    nameHint.value ||
    directory.nameOf(userId.value) ||
    t("profile.unknownUser"),
);
const avatarSeed = computed(
  () =>
    profile.value?.display_name ||
    nameHint.value ||
    directory.nameOf(userId.value) ||
    userId.value ||
    "?",
);
const shortId = computed(() => (userId.value ? userId.value.slice(0, 8) : ""));
const postsLabel = computed(
  () => t("profile.postsCount", { count: posts.value.length }) + (hasMore.value ? "+" : ""),
);
const hasAbout = computed(() => {
  const p = profile.value;
  return !!(
    p &&
    (p.bio || p.intro || p.city || p.country || p.handle || p.links?.length || p.work?.length || p.education?.length)
  );
});

const photoIds = computed(() => posts.value.flatMap((p) => p.media_ids ?? []));
const photoUrls = useMediaUrls(() => photoIds.value);
const lightbox = ref<string | null>(null);
useEscapeKey(
  computed(() => !!lightbox.value),
  () => (lightbox.value = null),
);

function joinedText(iso?: string): string {
  if (!iso) return "";
  try {
    return t("profile.joined", {
      date: new Date(iso).toLocaleDateString(locale.value, { year: "numeric", month: "long" }),
    });
  } catch {
    return "";
  }
}

function reset() {
  profile.value = null;
  posts.value = [];
  cursor.value = null;
  hasMore.value = false;
  tab.value = "posts";
  following.value = false;
  friendState.value = route.query.rel === "friends" ? "friends" : "none";
  pendingRequestId.value = undefined;
  relLoaded.value = false;
  followersCount.value = null;
  friendsCount.value = null;
  mutual.value = [];
  relFriendIds.value = [];
}

// Critical load = the profile itself. Posts / relationship / counts load
// independently so a single failure never blanks the whole page.
async function load() {
  loading.value = true;
  error.value = false;
  reset();
  if (isSelfRoute.value) {
    // auth.profile is already the full /profile/me record — render instantly
    // from cache, then refresh in the background.
    if (auth.profile) {
      profile.value = auth.profile;
      profileService.me().then((p) => (profile.value = p)).catch(() => {});
    } else {
      try {
        profile.value = await profileService.me();
      } catch {
        error.value = true;
        loading.value = false;
        return;
      }
    }
  } else if (handleParam.value) {
    try {
      profile.value = await profileService.get(handleParam.value);
      // If this is actually our own handle (auth.profile was unavailable when
      // isSelfRoute evaluated), enrich with the full /profile/me record.
      if (profile.value?.is_self) {
        profileService.me().then((p) => (profile.value = p)).catch(() => {});
      }
    } catch {
      error.value = true;
      loading.value = false;
      return;
    }
  }
  loading.value = false;
  // Seed the name directory so this user shows a real name elsewhere too.
  if (profile.value && userId.value) {
    directory.remember(
      userId.value,
      profile.value.display_name,
      profile.value.avatar_media_id,
      profile.value.handle,
    );
  }
  if (nameHint.value && idParam.value) directory.remember(idParam.value, nameHint.value);
  loadPosts();
  loadRelationship();
  loadCounts();
}

async function loadPosts() {
  if (!userId.value || profile.value?.restricted) return;
  loadingPosts.value = true;
  try {
    const page = await postService.byAuthor(userId.value);
    posts.value = page.data;
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch {
    posts.value = [];
  } finally {
    loadingPosts.value = false;
  }
}

async function loadMore() {
  if (!userId.value || !cursor.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await postService.byAuthor(userId.value, cursor.value);
    posts.value.push(...page.data);
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch {
    /* keep */
  } finally {
    loadingMore.value = false;
  }
}

async function loadRelationship() {
  if (!userId.value || isSelf.value) {
    relLoaded.value = true;
    return;
  }
  try {
    const [followingList, friendList, incoming, outgoing] = await Promise.all([
      graphService.followingIds().catch(() => [] as string[]),
      graphService.friends().catch(() => [] as string[]),
      graphService.incomingRequests().catch(() => [] as FriendRequest[]),
      graphService.outgoingRequests().catch(() => [] as FriendRequest[]),
    ]);
    following.value = followingList.includes(userId.value);
    if (friendList.includes(userId.value)) {
      friendState.value = "friends";
    } else {
      const inc = incoming.find((r) => r.from_user_id === userId.value);
      if (inc) {
        friendState.value = "pending_in";
        pendingRequestId.value = inc.id;
      } else if (outgoing.some((r) => r.to_user_id === userId.value)) {
        friendState.value = "pending_out";
      } else {
        friendState.value = "none";
      }
    }
  } catch {
    /* leave defaults */
  } finally {
    relLoaded.value = true;
  }
}

async function loadCounts() {
  const id = userId.value;
  if (!id) return;
  if (isSelf.value) {
    graphService.friends().then((f) => { friendsCount.value = f.length; relFriendIds.value = f; }).catch(() => {});
    graphService.followerIds().then((f) => (followersCount.value = f.length)).catch(() => {});
  } else {
    graphService.socialFriends(id).then((f) => { friendsCount.value = f.length; relFriendIds.value = f; }).catch(() => {});
    graphService.socialFollowers(id).then((f) => (followersCount.value = f.length)).catch(() => {});
    graphService.mutualFriends(id).then((m) => (mutual.value = m)).catch(() => {});
  }
}

const messaging = ref(false);
async function message() {
  if (!userId.value || messaging.value) return;
  messaging.value = true;
  try {
    const convo = await chatService.openDm(userId.value);
    router.push(`/messages/${convo.id}`);
  } catch {
    /* chat may be unavailable */
  } finally {
    messaging.value = false;
  }
}

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
    /* clipboard blocked */
  }
}

const blocked = ref(false);
const blocking = ref(false);
async function toggleBlock() {
  if (!userId.value || blocking.value) return;
  menuOpen.value = false;
  blocking.value = true;
  const next = !blocked.value;
  blocked.value = next;
  try {
    if (next) await graphService.block(userId.value);
    else await graphService.unblock(userId.value);
  } catch {
    blocked.value = !next;
  } finally {
    blocking.value = false;
  }
}

const showEdit = ref(false);
function onProfileSaved(fresh: Profile) {
  profile.value = fresh;
  showEdit.value = false;
}

watch(() => [route.params.handle, route.params.id, route.query.uid], load, { immediate: true });
</script>

<template>
  <AppShell :right="false">
    <div class="mx-auto w-full max-w-[1100px]">
      <div v-if="loading" class="card overflow-hidden">
        <div class="h-40 animate-pulse bg-gray-200 dark:bg-gray-800 sm:h-56" />
        <div class="px-4 pb-4">
          <div class="-mt-14 h-28 w-28 animate-pulse rounded-full border-4 border-white bg-gray-200 dark:border-gray-900 dark:bg-gray-700 sm:-mt-16" />
          <div class="mt-3 h-6 w-44 animate-pulse rounded bg-gray-200 dark:bg-gray-800" />
          <div class="mt-2 h-4 w-28 animate-pulse rounded bg-gray-200 dark:bg-gray-800" />
        </div>
      </div>

      <ErrorState v-else-if="error" @retry="load" />

      <template v-else>
        <!-- Hero -->
        <div class="card overflow-hidden">
          <div class="relative h-48 bg-gradient-to-r from-brand-100 to-brand-50 dark:from-brand-900/40 dark:to-gray-800 sm:h-64">
            <img v-if="cover" :src="cover" class="h-full w-full object-cover" alt="" />
          </div>

          <div class="px-4 pb-4 sm:px-6">
            <div class="-mt-16 flex flex-col gap-3 sm:-mt-20 sm:flex-row sm:items-end sm:justify-between">
              <span class="relative inline-block w-fit">
                <span class="block rounded-full border-4 border-white dark:border-gray-900">
                  <UserAvatar :name="avatarSeed" :media-id="profile?.avatar_media_id" :size="128" />
                </span>
                <span
                  v-if="userId && presence.isOnline(userId)"
                  class="absolute end-3 bottom-3 h-5 w-5 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
                  :title="t('presence.online')"
                />
              </span>

              <div class="flex flex-wrap items-center gap-2 pb-1">
                <button v-if="isSelf" class="btn-primary" @click="showEdit = true">
                  {{ t("profile.editProfile") }}
                </button>
                <template v-else-if="userId && relLoaded">
                  <FollowButton :user-id="userId" :following="following" />
                  <FriendButton :user-id="userId" :state="friendState" :request-id="pendingRequestId" />
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
                        @click="toggleBlock"
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
              <h1 class="text-2xl font-bold">{{ displayName }}</h1>
              <p v-if="profile?.intro" class="mt-0.5 text-sm text-gray-600 dark:text-gray-300">{{ profile.intro }}</p>
              <p v-if="profile?.handle" class="text-sm text-gray-500">@{{ profile.handle }}</p>
              <p v-else-if="shortId" class="text-xs text-gray-400">ID: {{ shortId }}…</p>

              <div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-500">
                <span class="font-medium text-gray-700 dark:text-gray-200">{{ postsLabel }}</span>
                <button
                  v-if="friendsCount !== null"
                  class="hover:text-brand-600 hover:underline"
                  @click="tab = 'friends'"
                >
                  {{ t("profile.friendsCount", { count: friendsCount }) }}
                </button>
                <RouterLink
                  v-if="followersCount !== null && isSelf"
                  to="/connections"
                  class="hover:text-brand-600 hover:underline"
                >
                  {{ t("profile.followersCount", { count: followersCount }) }}
                </RouterLink>
                <span v-else-if="followersCount !== null">{{ t("profile.followersCount", { count: followersCount }) }}</span>
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
                <span class="flex -space-x-2">
                  <UserAvatar v-for="m in mutual.slice(0, 3)" :key="m" :name="directory.nameOf(m) || m" :size="22" class="ring-2 ring-white dark:ring-gray-900" />
                </span>
                {{ t("profile.mutual", { count: mutual.length }) }}
              </div>

              <!-- Profile completion (self) -->
              <div
                v-if="isSelf && typeof profile?.completion_pct === 'number' && profile.completion_pct < 100"
                class="mt-3 rounded-xl bg-brand-50 p-3 dark:bg-brand-950/30"
              >
                <div class="flex items-center justify-between text-xs font-medium text-brand-700 dark:text-brand-300">
                  <span>{{ t("profile.completion", { pct: profile.completion_pct }) }}</span>
                  <button class="font-semibold underline" @click="showEdit = true">{{ t("profile.editProfile") }}</button>
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

        <!-- Posts overview: details sidebar (always visible) + feed -->
        <div v-show="tab === 'posts'" class="mt-4">
          <EmptyState v-if="profile?.restricted">{{ t("profile.private") }}</EmptyState>
          <div v-else class="gap-4 xl:grid xl:grid-cols-[360px_minmax(0,1fr)] xl:items-start">
            <!-- Details sidebar -->
            <div class="space-y-4 xl:sticky xl:top-20">
              <!-- Intro / About (full) -->
              <div v-if="hasAbout || isSelf" class="card p-4">
                <div class="mb-3 flex items-center justify-between">
                  <h3 class="text-base font-bold">{{ t("profile.intro") }}</h3>
                  <button v-if="isSelf" class="text-xs font-medium text-brand-600" @click="showEdit = true">
                    {{ t("profile.editProfile") }}
                  </button>
                </div>
                <div v-if="hasAbout" class="space-y-3 text-sm">
                  <p v-if="profile?.intro" class="font-medium text-gray-700 dark:text-gray-200">{{ profile.intro }}</p>
                  <p v-if="profile?.bio" class="whitespace-pre-line text-gray-600 dark:text-gray-300">{{ profile.bio }}</p>
                  <div v-if="profile?.work?.length" class="space-y-1.5">
                    <p v-for="w in profile.work" :key="w.id" class="flex items-start gap-2 text-gray-600 dark:text-gray-300">
                      <Briefcase class="mt-0.5 h-4 w-4 shrink-0 text-gray-400" />
                      <span>
                        <span class="font-medium">{{ w.title || "—" }}</span><span v-if="w.company"> · {{ w.company }}</span><span v-if="w.is_current" class="text-xs text-brand-600"> ({{ t("profile.present") }})</span>
                      </span>
                    </p>
                  </div>
                  <div v-if="profile?.education?.length" class="space-y-1.5">
                    <p v-for="e in profile.education" :key="e.id" class="flex items-start gap-2 text-gray-600 dark:text-gray-300">
                      <GraduationCap class="mt-0.5 h-4 w-4 shrink-0 text-gray-400" />
                      <span>
                        <span class="font-medium">{{ e.school }}</span><span v-if="e.field"> · {{ e.field }}</span><span v-if="e.start_year || e.end_year" class="text-xs text-gray-400"> ({{ e.start_year || "?" }}–{{ e.end_year || t("profile.present") }})</span>
                      </span>
                    </p>
                  </div>
                  <div v-if="profile?.links?.length" class="space-y-1.5">
                    <a v-for="l in profile.links" :key="l.id" :href="l.url" target="_blank" rel="noopener noreferrer" class="flex items-center gap-2 text-brand-600 hover:underline">
                      <LinkIcon class="h-4 w-4 shrink-0" /> <span class="truncate">{{ l.label || l.url }}</span>
                    </a>
                  </div>
                  <p v-if="profile?.city || profile?.country" class="flex items-center gap-2 text-gray-600 dark:text-gray-300">
                    <MapPin class="h-4 w-4 shrink-0 text-gray-400" /> {{ [profile?.city, profile?.country].filter(Boolean).join(", ") }}
                  </p>
                  <p v-if="profile?.created_at" class="flex items-center gap-2 text-gray-600 dark:text-gray-300">
                    <CalendarDays class="h-4 w-4 shrink-0 text-gray-400" /> {{ joinedText(profile.created_at) }}
                  </p>
                </div>
                <p v-else class="text-sm text-gray-400">{{ t("profile.limitedInfo") }}</p>
              </div>

              <!-- Photos -->
              <div v-if="photoUrls.length" class="card p-4">
                <div class="mb-2 flex items-center justify-between">
                  <h3 class="text-base font-bold">{{ t("profile.photos") }}</h3>
                  <button class="text-xs font-medium text-brand-600" @click="tab = 'photos'">{{ t("notifications.viewAll") }}</button>
                </div>
                <div class="grid grid-cols-3 gap-1.5">
                  <button
                    v-for="(src, i) in photoUrls.slice(0, 9)"
                    :key="i"
                    class="aspect-square overflow-hidden rounded-lg bg-gray-100 transition hover:opacity-90 dark:bg-gray-800"
                    @click="lightbox = src"
                  >
                    <img :src="src" class="h-full w-full object-cover" loading="lazy" decoding="async" alt="" />
                  </button>
                </div>
              </div>

              <!-- Friends -->
              <div v-if="relFriendIds.length" class="card p-4">
                <div class="mb-2 flex items-center justify-between">
                  <h3 class="text-base font-bold">
                    {{ t("profile.friends") }} <span class="text-sm font-normal text-gray-400">{{ friendsCount }}</span>
                  </h3>
                  <button class="text-xs font-medium text-brand-600" @click="tab = 'friends'">{{ t("notifications.viewAll") }}</button>
                </div>
                <div class="grid grid-cols-3 gap-2">
                  <RouterLink
                    v-for="id in relFriendIds.slice(0, 9)"
                    :key="id"
                    :to="{ name: 'profile-by-id', params: { id } }"
                    class="flex flex-col items-center gap-1 rounded-lg p-1.5 transition hover:bg-gray-100 dark:hover:bg-gray-800"
                  >
                    <UserAvatar :name="directory.nameOf(id) || id" :size="56" />
                    <span class="w-full truncate text-center text-[11px] text-gray-600 dark:text-gray-300">{{ directory.label(id) }}</span>
                  </RouterLink>
                </div>
              </div>
            </div>

            <!-- Feed -->
            <div class="mt-4 space-y-4 xl:mt-0">
              <LoadingSkeleton v-if="loadingPosts && !posts.length" :rows="2" />
              <EmptyState v-else-if="posts.length === 0">{{ t("feed.empty") }}</EmptyState>
              <PostCard
                v-for="post in posts"
                :key="post.id"
                :post="post"
                :author-name="displayName"
                :author-handle="profile?.handle"
                :author-avatar="profile?.avatar_media_id"
                @removed="posts = posts.filter((p) => p.id !== $event)"
              />
              <div v-if="hasMore" class="flex justify-center pt-1">
                <button class="btn-ghost" :disabled="loadingMore" @click="loadMore">
                  {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Photos -->
        <div v-show="tab === 'photos'" class="mt-4">
          <div class="card p-4">
            <h2 class="mb-3 text-base font-bold">{{ t("profile.photos") }}</h2>
            <EmptyState v-if="photoUrls.length === 0">{{ t("profile.noPhotos") }}</EmptyState>
            <div v-else class="grid grid-cols-3 gap-1.5 sm:grid-cols-4">
              <button
                v-for="(src, i) in photoUrls"
                :key="i"
                class="aspect-square overflow-hidden rounded-lg bg-gray-100 transition hover:opacity-90 dark:bg-gray-800"
                @click="lightbox = src"
              >
                <img :src="src" class="h-full w-full object-cover" loading="lazy" alt="" />
              </button>
            </div>
          </div>
        </div>

        <!-- Friends -->
        <div v-show="tab === 'friends'" class="mt-4">
          <div class="card p-4">
            <h2 class="mb-3 flex items-center justify-between text-base font-bold">
              <span>{{ t("profile.friends") }}</span>
              <span v-if="friendsCount !== null" class="text-sm font-normal text-gray-400">{{ friendsCount }}</span>
            </h2>
            <EmptyState v-if="relFriendIds.length === 0">{{ t("friends.none") }}</EmptyState>
            <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <RouterLink
                v-for="id in relFriendIds.slice(0, 30)"
                :key="id"
                :to="{ name: 'profile-by-id', params: { id } }"
                class="flex flex-col items-center gap-2 rounded-xl p-3 text-center transition hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                <span class="relative">
                  <UserAvatar :name="directory.nameOf(id) || id" :size="56" />
                  <span
                    v-if="presence.isOnline(id)"
                    class="absolute -end-0.5 -bottom-0.5 h-3 w-3 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
                  />
                </span>
                <span class="truncate text-xs font-medium">{{ directory.label(id) }}</span>
              </RouterLink>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- Lightbox -->
    <div v-if="lightbox" class="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 p-4" @click="lightbox = null">
      <button class="absolute end-4 top-4 rounded-full bg-white/15 p-2 text-white" :aria-label="t('feed.cancel')">
        <X class="h-5 w-5" />
      </button>
      <img :src="lightbox" class="max-h-[90vh] max-w-full rounded-lg object-contain" alt="" />
    </div>

    <EditProfileModal v-if="showEdit && profile" :profile="profile" @close="showEdit = false" @saved="onProfileSaved" />
  </AppShell>
</template>
