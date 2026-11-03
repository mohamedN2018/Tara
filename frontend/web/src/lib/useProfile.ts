// Everything behind a profile page: the profile itself, its timeline, the viewer's
// relationship to it and the counts. Each part loads on its own, so one failure
// never blanks the whole page.
import { computed, type reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { errorMessage } from "@/lib/errors";
import { useMediaUrl, useMediaUrls } from "@/lib/useMediaUrl";
import { chatService } from "@/services/chat";
import { type FriendState, graphService } from "@/services/graph";
import { postService } from "@/services/post";
import { profileService } from "@/services/profile";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";
import type { Post, Profile } from "@/types";

export function useProfile() {
  const { t, locale } = useI18n();
  const route = useRoute();
  const router = useRouter();
  const auth = useAuthStore();
  const directory = useDirectoryStore();
  const toasts = useToastStore();

  const profile = ref<Profile | null>(null);
  const posts = ref<Post[]>([]);
  const loading = ref(true);
  const loadingPosts = ref(false);
  const error = ref("");
  const postsError = ref(false);
  const tab = ref<"posts" | "photos" | "friends">("posts");

  const cursor = ref<string | null>(null);
  const hasMore = ref(false);
  const loadingMore = ref(false);
  // Guards against a slow response landing after navigating to another profile.
  let loadGeneration = 0;

  // Relationship + counts (real data from the graph service).
  const following = ref(false);
  const friendState = ref<FriendState>("none");
  const pendingRequestId = ref<string | undefined>(undefined);
  const relLoaded = ref(false);
  const relFailed = ref(false);
  const followersCount = ref<number | null>(null);
  const friendsCount = ref<number | null>(null);
  const mutual = ref<string[]>([]);
  const relFriendIds = ref<string[]>([]);

  const handleParam = computed(() => (route.params.handle as string) || "");
  const idParam = computed(() => (route.params.id as string) || "");

  const isSelfRoute = computed(() => {
    if (handleParam.value) return !!auth.profile && auth.profile.handle === handleParam.value;
    if (idParam.value) return auth.account?.id === idParam.value;
    return false;
  });

  const cover = useMediaUrl(() => profile.value?.cover_media_id);
  const isSelf = computed(() => profile.value?.is_self ?? isSelfRoute.value);
  // Posts, follows, friendships and DMs are all keyed by account_id, NOT the
  // profile record's PK.
  const userId = computed(
    () => profile.value?.account_id ?? (isSelf.value ? auth.account?.id : undefined) ?? (idParam.value || null),
  );
  const displayName = computed(
    () => profile.value?.display_name || directory.nameOf(userId.value) || t("profile.unknownUser"),
  );
  const postsLabel = computed(
    () => t("profile.postsCount", posts.value.length) + (hasMore.value ? "+" : ""),
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
    postsError.value = false;
    tab.value = "posts";
    following.value = false;
    friendState.value = "none";
    pendingRequestId.value = undefined;
    relLoaded.value = false;
    relFailed.value = false;
    blocked.value = false;
    followersCount.value = null;
    friendsCount.value = null;
    mutual.value = [];
    relFriendIds.value = [];
  }

  // Critical load = the profile itself. Posts / relationship / counts load
  // independently so a single failure never blanks the whole page.
  async function load() {
    const generation = ++loadGeneration;
    loading.value = true;
    error.value = "";
    reset();
    const refreshSelf = () =>
      profileService
        .me()
        .then((p) => {
          if (generation === loadGeneration) profile.value = p;
        })
        .catch(() => {}); // The cached record is already on screen.
    try {
      if (isSelfRoute.value && auth.profile) {
        // auth.profile is already the full /profile/me record — render instantly
        // from cache, then refresh in the background.
        profile.value = auth.profile;
        void refreshSelf();
      } else if (isSelfRoute.value) {
        profile.value = await profileService.me();
      } else {
        const loaded = handleParam.value
          ? await profileService.get(handleParam.value)
          : await profileService.getById(idParam.value);
        if (generation !== loadGeneration) return;
        profile.value = loaded;
        // If this is actually our own account (auth.profile was unavailable when
        // isSelfRoute evaluated), enrich with the full /profile/me record.
        if (loaded.is_self) void refreshSelf();
      }
    } catch (e) {
      if (generation !== loadGeneration) return;
      error.value = errorMessage(e);
      loading.value = false;
      return;
    }
    if (generation !== loadGeneration) return;
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
    loadPosts();
    loadRelationship();
    loadCounts();
  }

  async function loadPosts() {
    if (!userId.value || profile.value?.restricted) return;
    const generation = loadGeneration;
    loadingPosts.value = true;
    postsError.value = false;
    try {
      const page = await postService.timelinePage(userId.value);
      if (generation !== loadGeneration) return;
      posts.value = page.data;
      cursor.value = page.page.next_cursor;
      hasMore.value = page.page.has_more;
    } catch {
      if (generation === loadGeneration) postsError.value = true;
    } finally {
      if (generation === loadGeneration) loadingPosts.value = false;
    }
  }

  async function loadMore() {
    if (!userId.value || !cursor.value || loadingMore.value) return;
    const generation = loadGeneration;
    loadingMore.value = true;
    try {
      const page = await postService.timelinePage(userId.value, cursor.value);
      if (generation !== loadGeneration) return;
      posts.value.push(...page.data);
      cursor.value = page.page.next_cursor;
      hasMore.value = page.page.has_more;
    } catch (e) {
      toasts.error(e);
    } finally {
      loadingMore.value = false;
    }
  }

  async function loadRelationship() {
    if (!userId.value || isSelf.value) {
      relLoaded.value = true;
      return;
    }
    const generation = loadGeneration;
    const id = userId.value;
    try {
      const [followingList, friendList, incoming, outgoing] = await Promise.all([
        graphService.followingIds(),
        graphService.friends(),
        graphService.incomingRequests(),
        graphService.outgoingRequests(),
      ]);
      if (generation !== loadGeneration) return;
      following.value = followingList.includes(id);
      if (friendList.includes(id)) {
        friendState.value = "friends";
      } else {
        const inc = incoming.find((r) => r.from_user_id === id);
        if (inc) {
          friendState.value = "pending_in";
          pendingRequestId.value = inc.id;
        } else if (outgoing.some((r) => r.to_user_id === id)) {
          friendState.value = "pending_out";
        } else {
          friendState.value = "none";
        }
      }
    } catch (e) {
      // Don't offer "Add friend" to someone who may already be a friend.
      if (generation === loadGeneration) {
        relFailed.value = true;
        toasts.error(e);
      }
    } finally {
      if (generation === loadGeneration) relLoaded.value = true;
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
    } catch (e) {
      toasts.error(e);
    } finally {
      messaging.value = false;
    }
  }

  const blocked = ref(false);
  const blocking = ref(false);
  async function toggleBlock() {
    if (!userId.value || blocking.value) return;
    blocking.value = true;
    const next = !blocked.value;
    blocked.value = next;
    try {
      if (next) await graphService.block(userId.value);
      else await graphService.unblock(userId.value);
    } catch (e) {
      blocked.value = !next;
      toasts.error(e);
    } finally {
      blocking.value = false;
    }
  }

  watch(() => [route.params.handle, route.params.id], load, { immediate: true });

  return {
    profile,
    posts,
    loading,
    loadingPosts,
    error,
    postsError,
    tab,
    hasMore,
    loadingMore,
    following,
    friendState,
    pendingRequestId,
    relLoaded,
    relFailed,
    followersCount,
    friendsCount,
    mutual,
    relFriendIds,
    cover,
    isSelf,
    userId,
    displayName,
    postsLabel,
    hasAbout,
    photoUrls,
    messaging,
    blocked,
    blocking,
    joinedText,
    load,
    loadPosts,
    loadMore,
    message,
    toggleBlock,
  };
}

export type ProfileState = ReturnType<typeof reactive<ReturnType<typeof useProfile>>>;
