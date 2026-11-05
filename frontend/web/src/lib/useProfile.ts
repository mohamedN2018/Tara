// Everything behind a profile page: the profile itself, its timeline, the viewer's
// relationship to it and the counts. Each part loads on its own, so one failure
// never blanks the whole page.
import { computed, type reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { errorMessage, mediaErrorKey } from "@/lib/errors";
import { useMediaUrl, useMediaUrls } from "@/lib/useMediaUrl";
import { chatService } from "@/services/chat";
import { type FriendState, graphService } from "@/services/graph";
import { marketplaceService } from "@/services/marketplace";
import { mediaService } from "@/services/media";
import { postService } from "@/services/post";
import { profileService } from "@/services/profile";
import { relationshipsService } from "@/services/relationships";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";
import type { Post, Profile } from "@/types";

export type ProfileTab = "posts" | "about" | "friends" | "photos" | "reels" | "marketplace";
export type FriendsList = "all" | "mutual" | "followers" | "following";
const TABS: readonly ProfileTab[] = ["posts", "about", "friends", "photos", "reels", "marketplace"];
const LISTS: readonly FriendsList[] = ["all", "mutual", "followers", "following"];

export function tabFromQuery(q: unknown): ProfileTab {
  return TABS.includes(q as ProfileTab) ? (q as ProfileTab) : "posts";
}
export function listFromQuery(q: unknown): FriendsList {
  return LISTS.includes(q as FriendsList) ? (q as FriendsList) : "all";
}

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
  // The tab and the Friends sub-list live in the URL (?tab=about, ?tab=friends&list=followers)
  // so menus and notifications can deep-link and a refresh keeps the place.
  const tab = ref<ProfileTab>(tabFromQuery(route.query.tab));
  const friendsList = ref<FriendsList>(listFromQuery(route.query.list));

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
  const followingCount = ref<number | null>(null);
  const friendsCount = ref<number | null>(null);
  // Lists for the Friends tab, loaded when the tab opens. null = not loaded; "hidden" =
  // the owner's graph privacy hides it from you (server 404), so the sub-tab is left out;
  // "error" = any other failure (5xx, network): the sub-tab stays and offers a retry.
  const followerList = ref<string[] | null | "hidden" | "error">(null);
  const followingList = ref<{ target_id: string; target_type: string }[] | null | "hidden" | "error">(null);
  const friendsHidden = ref(false);
  const mutual = ref<string[]>([]);
  const relFriendIds = ref<string[]>([]);
  // The Marketplace tab shows only when marketplace's seller page would open for
  // this viewer (its rule: 404 when blocked either way, unknown, or nothing public).
  const hasShop = ref(false);
  const shopChecked = ref(false);

  const handleParam = computed(() => (route.params.handle as string) || "");
  const idParam = computed(() => (route.params.id as string) || "");

  const isSelfRoute = computed(() => {
    if (handleParam.value) return !!auth.profile && auth.profile.handle === handleParam.value;
    if (idParam.value) return auth.account?.id === idParam.value;
    return false;
  });

  const cover = useMediaUrl(() => profile.value?.cover_media_id);
  const avatar = useMediaUrl(() => profile.value?.avatar_media_id);
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
    tab.value = tabFromQuery(route.query.tab);
    friendsList.value = listFromQuery(route.query.list);
    following.value = false;
    friendState.value = "none";
    pendingRequestId.value = undefined;
    relLoaded.value = false;
    relFailed.value = false;
    followersCount.value = null;
    followingCount.value = null;
    friendsCount.value = null;
    followerList.value = null;
    followingList.value = null;
    friendsHidden.value = false;
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
    // The timeline only fails on an upstream 5xx / network blip (post or graph restarting; the list
    // itself never 404s for a profile you can open), so retry once before showing the error state.
    const transient = (e: unknown) => {
      const status = (e as { response?: { status?: number } })?.response?.status;
      return status === undefined || status >= 500;
    };
    const author = userId.value;
    const fetchPage = () =>
      postService.timelinePage(author).catch(async (e) => {
        if (!transient(e) || generation !== loadGeneration) throw e;
        await new Promise((r) => setTimeout(r, 600));
        return postService.timelinePage(author);
      });
    try {
      const page = await fetchPage();
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
          // Kept so "Cancel request" can call reject/ on our own request.
          pendingRequestId.value = outgoing.find((r) => r.to_user_id === id)?.id;
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
    const generation = loadGeneration;
    const live = () => generation === loadGeneration;
    // Counts come from graph's counts endpoint (gated by counts_visibility: a
    // 404 leaves them hidden). Lists are gated separately.
    relationshipsService
      .counts(id)
      .then((c) => {
        if (!live()) return;
        friendsCount.value = c.friends_count;
        followersCount.value = c.followers_count;
        followingCount.value = c.following_count;
      })
      .catch(() => {});
    if (isSelf.value) {
      graphService
        .friends()
        .then((f) => {
          if (live()) relFriendIds.value = f;
        })
        .catch(() => {});
    } else {
      graphService
        .socialFriends(id)
        .then((f) => {
          if (live()) relFriendIds.value = f;
        })
        .catch(() => {
          if (live()) friendsHidden.value = true;
        });
      graphService
        .mutualFriends(id)
        .then((m) => {
          if (live()) mutual.value = m;
        })
        .catch(() => {});
    }
  }

  /** Followers / following for the Friends tab (first view; `retry` reloads a failed one). */
  function loadFollowLists(retry = false) {
    const id = userId.value;
    if (!id) return;
    const generation = loadGeneration;
    const live = () => generation === loadGeneration;
    const failed = (e: unknown) => ((e as { response?: { status?: number } })?.response?.status === 404 ? "hidden" : "error");
    if (retry && followerList.value === "error") followerList.value = null;
    if (retry && followingList.value === "error") followingList.value = null;
    if (followerList.value === null) {
      const req = isSelf.value ? graphService.followerIds() : graphService.socialFollowers(id);
      req
        .then((ids) => {
          if (live()) followerList.value = ids;
        })
        .catch((e) => {
          if (live()) followerList.value = failed(e);
        });
    }
    if (followingList.value === null) {
      graphService
        .socialFollowing(id)
        .then((rows) => {
          if (live()) followingList.value = rows;
        })
        .catch((e) => {
          if (live()) followingList.value = failed(e);
        });
    }
  }

  /** Friendship changed from the header button: keep the counts honest. */
  function onFriendChange(next: FriendState, requestId?: string) {
    const was = friendState.value;
    friendState.value = next;
    pendingRequestId.value = requestId;
    if (friendsCount.value !== null && was !== next) {
      if (next === "friends") friendsCount.value += 1;
      else if (was === "friends") friendsCount.value = Math.max(0, friendsCount.value - 1);
    }
    const me = auth.account?.id;
    if (me && next === "friends" && !relFriendIds.value.includes(me)) relFriendIds.value = [me, ...relFriendIds.value];
    if (me && was === "friends" && next !== "friends") relFriendIds.value = relFriendIds.value.filter((x) => x !== me);
  }

  /** Follow toggled from the header (Follow button or the Friends menu). */
  function onFollowChange(on: boolean) {
    if (following.value === on) return;
    following.value = on;
    if (followersCount.value !== null) followersCount.value = Math.max(0, followersCount.value + (on ? 1 : -1));
  }

  // ---- own avatar / cover: upload, change, remove (PATCH /profile/me/) ----
  const savingPhoto = ref<"" | "avatar" | "cover">("");
  async function setPhoto(kind: "avatar" | "cover", file: File | null) {
    if (!isSelf.value || savingPhoto.value) return;
    savingPhoto.value = kind;
    try {
      const id = file ? (await mediaService.upload(file, "image")).id : null;
      const field = kind === "avatar" ? "avatar_media_id" : "cover_media_id";
      const fresh = await profileService.update({ [field]: id });
      profile.value = { ...(profile.value ?? fresh), ...fresh };
      if (userId.value) directory.remember(userId.value, fresh.display_name, fresh.avatar_media_id, fresh.handle);
      void auth.loadProfile();
      toasts.success(t(file ? "people.hero.photoUpdated" : "people.hero.photoRemoved"));
    } catch (e) {
      const media = mediaErrorKey(e);
      if (media) toasts.push({ text: t(media), icon: "error" });
      else toasts.error(e);
    } finally {
      savingPhoto.value = "";
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

  watch(() => [route.params.handle, route.params.id], load, { immediate: true });

  // URL <-> tab. Only the query changes, so the profile is not reloaded.
  watch(
    () => [route.query.tab, route.query.list],
    ([q, l]) => {
      tab.value = tabFromQuery(q);
      friendsList.value = listFromQuery(l);
    },
  );
  watch([tab, friendsList], ([tb, list]) => {
    const query = { ...route.query };
    if (tb === "posts") delete query.tab;
    else query.tab = tb;
    if (tb === "friends" && list !== "all") query.list = list;
    else delete query.list;
    if (query.tab === route.query.tab && query.list === route.query.list) return;
    void router.replace({ query });
  });
  watch(
    [tab, userId],
    ([tb]) => {
      // Load both follow lists as soon as the Friends tab opens, so their sub-tabs show (or stay
      // out) before anyone clicks them instead of vanishing after the click.
      if (tb === "friends") loadFollowLists();
    },
    { immediate: true },
  );

  // Ask marketplace once the profile itself has loaded (a hidden profile asks nothing).
  async function checkShop(id: string | null) {
    hasShop.value = false;
    shopChecked.value = false;
    if (!id) return;
    try {
      await marketplaceService.seller(id);
      if (userId.value === id) hasShop.value = true;
    } catch {
      // 404 (no public listings, blocked) or marketplace down: no tab.
    } finally {
      if (userId.value === id) shopChecked.value = true;
    }
  }
  watch(
    () => (profile.value && !profile.value.restricted ? userId.value : null),
    (id) => void checkShop(id ?? null),
    { immediate: true },
  );
  // A ?tab=marketplace link to someone with no shop lands on Posts.
  watch([tab, shopChecked, hasShop], ([tb, checked, has]) => {
    if (tb === "marketplace" && checked && !has) tab.value = "posts";
  });

  /** Switch section (and Friends sub-list); the URL follows through the watcher above. */
  function openTab(next: ProfileTab, list?: FriendsList) {
    tab.value = next;
    if (list) friendsList.value = list;
  }
  function setFriendsList(list: FriendsList) {
    friendsList.value = list;
  }
  /** Merge a saved change from the About editors into the loaded profile. */
  function patchProfile(changes: Partial<Profile>) {
    if (profile.value) profile.value = { ...profile.value, ...changes };
  }

  return {
    openTab,
    setFriendsList,
    patchProfile,
    profile,
    posts,
    loading,
    loadingPosts,
    error,
    postsError,
    tab,
    hasShop,
    hasMore,
    loadingMore,
    following,
    friendState,
    pendingRequestId,
    relLoaded,
    relFailed,
    followersCount,
    followingCount,
    friendsCount,
    followerList,
    followingList,
    friendsHidden,
    friendsList,
    avatar,
    savingPhoto,
    setPhoto,
    onFriendChange,
    onFollowChange,
    loadFollowLists,
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
    joinedText,
    load,
    loadPosts,
    loadMore,
    message,
  };
}

export type ProfileState = ReturnType<typeof reactive<ReturnType<typeof useProfile>>>;
