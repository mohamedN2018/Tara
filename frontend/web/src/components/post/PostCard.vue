<script setup lang="ts">
import {
  Ban,
  BellOff,
  Bookmark,
  BookmarkMinus,
  Clock,
  Download,
  EyeOff,
  Flag,
  FolderPlus,
  Globe,
  Info,
  Link2,
  MessageSquareOff,
  MoreHorizontal,
  PenSquare,
  Pin,
  PinOff,
  Star,
  StarOff,
  Trash2,
  UserMinus,
  Users,
  X,
} from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { type RouteLocationRaw, useRoute } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import VideoPlayer from "@/components/media/VideoPlayer.vue";
import AudienceDialog from "@/components/post/AudienceDialog.vue";
import CommentInput from "@/components/post/CommentInput.vue";
import CommentItem from "@/components/post/CommentItem.vue";
import CommentList from "@/components/post/CommentList.vue";
import ComposerDialog from "@/components/post/ComposerDialog.vue";
import LinkPreviewCard from "@/components/post/LinkPreviewCard.vue";
import MediaGrid from "@/components/post/MediaGrid.vue";
import MediaTheater from "@/components/post/MediaTheater.vue";
import PostTheaterPanel, { type PanelState } from "@/components/post/PostTheaterPanel.vue";
import PollCard from "@/components/post/PollCard.vue";
import PostActions from "@/components/post/PostActions.vue";
import PostComposerMeta from "@/components/post/PostComposerMeta.vue";
import ReactionsDialog from "@/components/post/ReactionsDialog.vue";
import RichText from "@/components/post/RichText.vue";
import SaveToCollection from "@/components/post/SaveToCollection.vue";
import ShareBox from "@/components/post/ShareBox.vue";
import SharedPostCard from "@/components/post/SharedPostCard.vue";
import SharesDialog from "@/components/post/SharesDialog.vue";
import WhyThisPost from "@/components/post/WhyThisPost.vue";
import ConfirmActionDialog from "@/components/social/ConfirmActionDialog.vue";
import NameHoverCard from "@/components/social/NameHoverCard.vue";
import { AUDIENCE_ICON, audienceLabel } from "@/lib/audiences";
import { downloadMedia } from "@/lib/downloadMedia";
import { relativeTime } from "@/lib/format";
import { itemKey, surfaceForRoute, track } from "@/lib/signals";
import { applyReactionChange } from "@/lib/reactionCounts";
import { hasLink } from "@/lib/richText";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useImpression } from "@/lib/useImpression";
import { useMediaViewer } from "@/lib/useMediaViewer";
import { useRelationshipPrefs } from "@/lib/useRelationshipPrefs";
import type { FeedReason } from "@/services/feed";
import { graphService } from "@/services/graph";
import { groupPostsService } from "@/services/groups";
import { type Comment, COMMENT_POLICIES, type CommentPolicy, postService, REPORT_ERRORS } from "@/services/post";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { usePageDirectoryStore } from "@/stores/pageDirectory";
import { useToastStore } from "@/stores/toasts";
import type { Post } from "@/types";

const props = withDefaults(
  defineProps<{
    post: Post;
    authorName?: string;
    authorHandle?: string;
    authorAvatar?: string | null;
    startCommentsOpen?: boolean;
    /** Scroll the open comments to this comment (and its thread root, if known). */
    focusCommentId?: string | null;
    focusThreadId?: string | null;
    /** In a group feed: the viewer may delete posts and comments (group moderator+). */
    groupModerator?: boolean;
    /** On a page's timeline: the viewer may delete the page's posts (page moderator+, T3). */
    pageModerator?: boolean;
    /** On a page's timeline: the viewer may edit the page's posts (owner, admin, editor). */
    pageEditor?: boolean;
    /** In a group feed: the viewer may pin announcements. */
    groupCanPin?: boolean;
    /** In the home feed: offer "Hide post" (X and menu); the feed handles `hide`. */
    hideable?: boolean;
    /** In the home feed: offer "Snooze for 30 days"; the feed handles `snooze`. */
    snoozable?: boolean;
    /** In the home feed: why the item reached this viewer (feed's reason). */
    feedReason?: FeedReason | null;
    /** The feed's sort, shown in "Why am I seeing this post?". */
    feedMode?: string | null;
  }>(),
  {
    startCommentsOpen: false,
    focusCommentId: null,
    focusThreadId: null,
    groupModerator: false,
    pageModerator: false,
    pageEditor: false,
    groupCanPin: false,
    hideable: false,
    snoozable: false,
    feedReason: null,
    feedMode: null,
  },
);
const emit = defineEmits<{
  removed: [id: string];
  shared: [post: Post];
  pinned: [id: string, pinned: boolean];
  hide: [post: Post];
  snooze: [post: Post];
  /** The viewer muted or unfollowed the author: the feed drops their items. */
  "author-gone": [post: Post];
  /** The viewer unsaved the post (the Saved page drops it). */
  unsaved: [id: string];
}>();

const { t } = useI18n();
const auth = useAuthStore();
const directory = useDirectoryStore();
// Posts published as a page (T3): the author is the page, named from the pages directory.
const pageDirectory = usePageDirectoryStore();
const byPage = computed(() => props.post.author_type === "page");
const toasts = useToastStore();

// The post as last returned by the server (an edit replaces it).
const current = ref<Post>(props.post);
watch(
  () => props.post,
  (p) => (current.value = p),
);

const authorDisplay = computed(
  () => props.authorName || (byPage.value ? pageDirectory.label(props.post.author_id) : directory.label(props.post.author_id)),
);
const avatarId = computed(
  () => props.authorAvatar ?? (byPage.value ? pageDirectory.avatarOf(props.post.author_id) : directory.avatarOf(props.post.author_id)),
);
// Always navigate by account id (post.author_id) — that route loads the
// author's posts. The handle route can't resolve posts for other users.
const authorTo = computed<RouteLocationRaw>(() => ({
  name: byPage.value ? "page-by-id" : "profile-by-id",
  params: { id: props.post.author_id },
}));
const isAuthor = computed(() => auth.account?.id === props.post.author_id);
const isUserAuthor = computed(() => (props.post.author_type ?? "user") === "user");
// A feed snapshot holds at most an excerpt: saving it would truncate the post.
const canEdit = computed(
  () => (isAuthor.value || (byPage.value && props.pageEditor)) && !props.post.partial && props.post.type !== "poll",
);
// Audience: author, published outside a group, from live data.
const canEditAudience = computed(
  () => isAuthor.value && !props.post.partial && !current.value.group_id && current.value.audience !== "group",
);
const isShare = computed(() => !!props.post.shared_post_id);
// Hiding your own post from your feed isn't offered.
const canHide = computed(() => props.hideable && !isAuthor.value);
const canSnooze = computed(() => props.snoozable && !isAuthor.value);
// Unfollow only removes follow items (feed's rule), so it is offered for those only.
const canUnfollow = computed(() => !isAuthor.value && props.feedReason === "follow");
const canPeoplePrefs = computed(() => !isAuthor.value && isUserAuthor.value && !!auth.account);

function closeMenu() {
  menuOpen.value = false;
}
function hidePost() {
  closeMenu();
  emit("hide", props.post);
}
function snoozeAuthor() {
  closeMenu();
  emit("snooze", props.post);
}

// The server builds the preview after the post is saved, so a post just written
// doesn't have it yet.
const PREVIEW_REFETCH_MS = 2500;
const linkPreview = ref(props.post.link_preview ?? null);
let previewTimer: number | undefined;
function refetchPreviewSoon() {
  window.clearTimeout(previewTimer);
  previewTimer = window.setTimeout(async () => {
    try {
      linkPreview.value = (await postService.get(props.post.id)).link_preview ?? null;
    } catch {
      // Shown on the next load.
    }
  }, PREVIEW_REFETCH_MS);
}

const audienceIcon = computed(() => AUDIENCE_ICON[current.value.audience] ?? Globe);
const audienceName = computed(() => t(audienceLabel(current.value.audience)));
const fullTime = computed(() => {
  try {
    return new Date(props.post.created_at).toLocaleString();
  } catch {
    return "";
  }
});

const menuOpen = ref(false);
useEscapeKey(menuOpen, () => (menuOpen.value = false));
watch(menuOpen, (open) => {
  if (open && canPeoplePrefs.value) void prefs.ensure();
});
// Group moderators delete others' posts; the author deletes their own.
const canRemove = computed(() => isAuthor.value || props.groupModerator || (byPage.value && props.pageModerator));
const pinned = ref(!!props.post.pinned_at);
const pinning = ref(false);
async function togglePin() {
  if (pinning.value) return;
  closeMenu();
  pinning.value = true;
  const next = !pinned.value;
  try {
    if (next) await groupPostsService.pin(props.post.id);
    else await groupPostsService.unpin(props.post.id);
    pinned.value = next;
    toasts.success(t(next ? "groups.post.pinned" : "groups.post.unpinned"));
    emit("pinned", props.post.id, next);
  } catch (e) {
    toasts.error(e);
  } finally {
    pinning.value = false;
  }
}
const removing = ref(false);
async function remove() {
  if (removing.value) return;
  removing.value = true;
  try {
    await postService.remove(props.post.id);
    emit("removed", props.post.id);
  } catch (e) {
    toasts.error(e);
  } finally {
    removing.value = false;
    closeMenu();
  }
}

// Edit (author only): the composer in "edit published post" mode.
const localBody = ref(props.post.body);
const edited = ref(false);
const editing = ref(false);
function startEdit() {
  closeMenu();
  if (!canEdit.value) return;
  editing.value = true;
}
function onEdited(updated: Post) {
  const before = localBody.value;
  current.value = { ...current.value, ...updated };
  localBody.value = updated.body;
  commentPolicy.value = updated.comment_policy ?? commentPolicy.value;
  edited.value = true;
  if (before !== updated.body) refetchPreviewSoon();
}

// Audience (author only).
const editingAudience = ref(false);
function startAudience() {
  closeMenu();
  if (canEditAudience.value) editingAudience.value = true;
}
function onAudience(updated: Post) {
  current.value = { ...current.value, ...updated };
  toasts.success(t("postsFeed.audience.saved"));
}

// Who can comment (author). The server enforces it; this only sets it.
const commentPolicy = ref<CommentPolicy>(props.post.comment_policy ?? "everyone");
const POLICY_LABEL: Record<CommentPolicy, string> = {
  everyone: "post.commentPolicyEveryone",
  friends: "post.commentPolicyFriends",
  off: "post.commentPolicyOff",
};
async function setPolicy(policy: CommentPolicy) {
  closeMenu();
  if (policy === commentPolicy.value) return;
  const prev = commentPolicy.value;
  commentPolicy.value = policy;
  try {
    await postService.setCommentPolicy(props.post.id, policy);
  } catch (e) {
    commentPolicy.value = prev;
    toasts.error(e);
  }
}

// Report (non-author)
const showReport = ref(false);
const reportReason = ref("");
const reported = ref(false);
async function submitReport() {
  if (!reportReason.value.trim()) return;
  try {
    await postService.report(props.post.id, reportReason.value.trim());
    reported.value = true;
    showReport.value = false;
    reportReason.value = "";
  } catch (e) {
    toasts.error(e, REPORT_ERRORS);
  }
}

// Copy link (everyone).
async function copyLink() {
  closeMenu();
  const url = `${window.location.origin}/posts/${props.post.id}`;
  try {
    await navigator.clipboard.writeText(url);
    toasts.success(t("postsFeed.menu.linkCopied"));
  } catch {
    toasts.push({ text: t("postsFeed.menu.copyFailed"), icon: "error" });
  }
}

// Download media (signed URL). One file downloads at once; several open the
// viewer, which downloads the photo on screen.
const downloading = ref(false);
async function downloadFromMenu() {
  closeMenu();
  if (mediaIds.value.length > 1 && props.post.type !== "video" && props.post.type !== "reel") {
    viewer.open(0);
    return;
  }
  const id = mediaIds.value[0];
  if (!id || downloading.value) return;
  downloading.value = true;
  try {
    await downloadMedia(id);
  } catch {
    toasts.push({ text: t("postsFeed.media.downloadFailed"), icon: "error" });
  } finally {
    downloading.value = false;
  }
}

// Why am I seeing this post? (home feed)
const showWhy = ref(false);

// Mute / favorites / block / unfollow the author (graph). The lists come from the
// one shared store the profile menu and Connections use, so every surface agrees.
const prefs = useRelationshipPrefs();
const prefBusy = ref(false);
const isFavorite = computed(() => prefs.has("favorites", props.post.author_id));
const isMuted = computed(() => prefs.has("mutes", props.post.author_id));
async function togglePref(kind: "favorites" | "mutes") {
  if (prefBusy.value) return;
  closeMenu();
  prefBusy.value = true;
  const on = !prefs.has(kind, props.post.author_id);
  const name = authorDisplay.value;
  try {
    await prefs.set(kind, props.post.author_id, on);
    if (kind === "mutes") {
      toasts.success(t(on ? "postsFeed.menu.muted" : "postsFeed.menu.unmuted", { name }));
      if (on) emit("author-gone", props.post);
    } else {
      toasts.success(t(on ? "postsFeed.menu.favorited" : "postsFeed.menu.unfavorited", { name }));
    }
  } catch (e) {
    toasts.error(e, { favorites_limit: "people.actions.favoritesLimit" });
  } finally {
    prefBusy.value = false;
  }
}
// Block asks first; the feed then drops the author's items (graph filters them server-side too).
const confirmBlock = ref(false);
async function blockAuthor() {
  if (prefBusy.value) return;
  prefBusy.value = true;
  try {
    await prefs.set("blocks", props.post.author_id, true);
    toasts.success(t("postsFeed.menu.blocked", { name: authorDisplay.value }));
    confirmBlock.value = false;
    emit("author-gone", props.post);
  } catch (e) {
    toasts.error(e);
  } finally {
    prefBusy.value = false;
  }
}
async function unfollow() {
  if (prefBusy.value) return;
  closeMenu();
  prefBusy.value = true;
  try {
    if (isUserAuthor.value) await graphService.unfollow(props.post.author_id);
    else await graphService.unfollowPage(props.post.author_id);
    toasts.success(t("postsFeed.menu.unfollowed", { name: authorDisplay.value }));
    emit("author-gone", props.post);
  } catch (e) {
    toasts.error(e);
  } finally {
    prefBusy.value = false;
  }
}

const myReaction = ref<string | null>(props.post.my_reaction ?? null);
const isSaved = ref(props.post.is_saved ?? false);
const reactionCount = ref(props.post.reaction_count);
const reactionCounts = ref<Record<string, number>>({ ...(props.post.reaction_counts ?? {}) });
const commentCount = ref(props.post.comment_count);
const shareCount = ref(props.post.share_count);
const showComments = ref(false);
const commentsMounted = ref(false);
const showReactions = ref(false);
const showShares = ref(false);

// Photos: grid in the card, full-screen viewer kept in `?view=<post>:<index>`.
const mediaIds = computed(() => props.post.media_ids ?? []);
const viewer = useMediaViewer(
  () => props.post.id,
  () => mediaIds.value.length,
);

// Names we genuinely know — used to label comments (others fall back to a short
// id). Never invents a name.
const knownNames = computed(() => {
  const map: Record<string, string> = {};
  if (props.authorName) map[props.post.author_id] = props.authorName;
  if (auth.account?.id) map[auth.account.id] = t("post.you");
  return map;
});

async function onReact(type: string) {
  const prev = myReaction.value;
  if (prev === type) return;
  const before = reactionCounts.value;
  if (prev === null) reactionCount.value += 1;
  myReaction.value = type;
  reactionCounts.value = applyReactionChange(before, prev, type);
  try {
    await postService.react(props.post.id, type);
  } catch (e) {
    myReaction.value = prev;
    reactionCounts.value = before;
    if (prev === null) reactionCount.value -= 1;
    toasts.error(e);
  }
}

async function onUnreact() {
  const prev = myReaction.value;
  if (prev === null) return;
  const before = reactionCounts.value;
  myReaction.value = null;
  reactionCount.value -= 1;
  reactionCounts.value = applyReactionChange(before, prev, null);
  try {
    await postService.unreact(props.post.id);
  } catch (e) {
    myReaction.value = prev;
    reactionCounts.value = before;
    reactionCount.value += 1;
    toasts.error(e);
  }
}

// The theater's panel reacts and comments on its own: keep this card in step.
function onPanelChanged(state: PanelState) {
  myReaction.value = state.myReaction;
  reactionCount.value = state.reactionCount;
  reactionCounts.value = state.reactionCounts;
  if (state.commentCount !== commentCount.value) {
    commentCount.value = state.commentCount;
    commentsMounted.value = false; // the full list reloads next time it opens
  }
}
function shareFromTheater() {
  viewer.close();
  sharing.value = true;
}

const JUST_POSTED_MS = 15_000;
onMounted(() => {
  if (props.startCommentsOpen) toggleComments();
  const fresh = Date.now() - new Date(props.post.created_at).getTime() < JUST_POSTED_MS;
  if (fresh && !linkPreview.value && isAuthor.value && hasLink(localBody.value)) refetchPreviewSoon();
});
onBeforeUnmount(() => window.clearTimeout(previewTimer));

function toggleComments() {
  showComments.value = !showComments.value;
  if (showComments.value) commentsMounted.value = true;
}

// Tara Intelligence signals (WP 2.8): a card half on screen for 1 s is an
// impression; opening its comments or its media is an open. Ids only.
const route = useRoute();
const signalSurface = computed(() => surfaceForRoute(route?.name));
const cardEl = ref<HTMLElement | null>(null);
useImpression(cardEl, () => ({ item: itemKey("post", props.post.id), surface: signalSurface.value }));
const signalOpen = () => track({ t: "post_open", item: itemKey("post", props.post.id), surface: signalSurface.value });
watch(showComments, (open) => open && signalOpen());
watch(
  () => viewer.index.value,
  (index) => index !== null && signalOpen(),
);
const videoItem = computed(() => itemKey(props.post.type === "reel" ? "reel" : "video", props.post.id));

// Inline preview (plan 08, 2B): up to two comments the post serializer sends as
// `top_comments` (2C), which the server filters for blocks. A server without the
// field sends none, and only the comment box shows.
const PREVIEW_MAX = 2;
const previewComments = ref<Comment[]>(
  ((props.post as Post & { top_comments?: Comment[] }).top_comments ?? []).slice(0, PREVIEW_MAX),
);
const moreToView = computed(() => commentCount.value > previewComments.value.length);
const previewBusyId = ref<string | null>(null);
const inlineSubmitting = ref(false);
const previewReported = ref(new Set<string>());

function replacePreview(c: Comment) {
  previewComments.value = previewComments.value.map((x) => (x.id === c.id ? c : x));
}

/** Gone from the full list (or already gone on the server): a root takes its replies along. */
function dropPreview(c: Pick<Comment, "id">) {
  previewComments.value = previewComments.value.filter((x) => x.id !== c.id && x.parent_id !== c.id);
}

async function submitInline(body: string) {
  if (inlineSubmitting.value) return;
  inlineSubmitting.value = true;
  try {
    const created = await postService.addComment(props.post.id, body);
    previewComments.value = [...previewComments.value.filter((c) => c.id !== created.id), created];
    commentCount.value += 1;
    // The full list loads afresh next time it opens.
    commentsMounted.value = false;
  } catch (e) {
    toasts.error(e);
  } finally {
    inlineSubmitting.value = false;
  }
}

async function editPreview(c: Comment, body: string) {
  previewBusyId.value = c.id;
  try {
    replacePreview({ ...c, ...(await postService.editComment(c.id, body)) });
  } catch (e) {
    toasts.error(e);
  } finally {
    previewBusyId.value = null;
  }
}

async function removePreview(c: Comment) {
  previewBusyId.value = c.id;
  try {
    const { comment_count } = await postService.deleteComment(c.id);
    previewComments.value = previewComments.value.filter((x) => x.id !== c.id);
    commentCount.value = comment_count;
    commentsMounted.value = false;
  } catch (e) {
    // 404: deleted already (elsewhere, or hidden from us): it has no place here.
    if ((e as { response?: { status?: number } })?.response?.status === 404) dropPreview(c);
    else toasts.error(e);
  } finally {
    previewBusyId.value = null;
  }
}

async function reactPreview(c: Comment, type: string | null) {
  const had = !!c.my_reaction;
  const optimistic: Comment = {
    ...c,
    my_reaction: type,
    reaction_count: Math.max(0, (c.reaction_count ?? 0) + (type && !had ? 1 : !type && had ? -1 : 0)),
  };
  replacePreview(optimistic);
  try {
    if (type) replacePreview({ ...optimistic, reaction_count: await postService.reactComment(c.id, type) });
    else await postService.unreactComment(c.id);
  } catch (e) {
    replacePreview(c);
    toasts.error(e);
  }
}

async function reportPreview(c: Comment, reason: string) {
  try {
    await postService.reportComment(c.id, reason);
    previewReported.value = new Set(previewReported.value).add(c.id);
  } catch (e) {
    toasts.error(e, REPORT_ERRORS);
  }
}

function previewName(id: string): string {
  return knownNames.value[id] || directory.label(id);
}

const sharing = ref(false);
function onShared(post: Post) {
  sharing.value = false;
  shareCount.value += 1;
  emit("shared", post);
}

// Save (menu): into the default collection; "Add to collection" picks another.
const savingTo = ref(false);
async function toggleSave() {
  closeMenu();
  const next = !isSaved.value;
  isSaved.value = next;
  try {
    if (next) await postService.save(props.post.id);
    else await postService.unsave(props.post.id);
    if (!next) emit("unsaved", props.post.id);
  } catch (e) {
    isSaved.value = !next;
    toasts.error(e);
  }
}
function openCollections() {
  closeMenu();
  savingTo.value = true;
}

const item =
  "flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-start text-sm font-medium transition hover:bg-gray-100 disabled:opacity-60 dark:hover:bg-gray-800";
const iconCls = "h-5 w-5 shrink-0 text-gray-600 dark:text-gray-300";
</script>

<template>
  <article ref="cardEl" class="card p-4 sm:p-5" :data-post-id="post.id">
    <header class="flex items-center gap-3">
      <RouterLink :to="authorTo" :aria-label="authorDisplay">
        <UserAvatar :name="authorDisplay" :media-id="avatarId" :size="44" />
      </RouterLink>
      <div class="min-w-0">
        <NameHoverCard :kind="byPage ? 'page' : 'user'" :id="post.author_id" class="block min-w-0">
          <RouterLink :to="authorTo" class="block truncate text-[15px] font-bold text-gray-900 hover:text-brand-600 dark:text-white dark:hover:text-brand-300" data-testid="post-author-name">
            <bdi>{{ authorDisplay }}</bdi>
          </RouterLink>
        </NameHoverCard>
        <PostComposerMeta :post="current" />
        <div class="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
          <RouterLink :to="`/posts/${post.id}`" class="hover:underline" :title="fullTime">
            {{ relativeTime(post.created_at) }}
          </RouterLink>
          <span aria-hidden="true">·</span>
          <!-- The author changes the audience from its icon, as on the reference. -->
          <button
            v-if="canEditAudience"
            type="button"
            class="rounded-full p-0.5 transition hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
            :aria-label="t('postsFeed.audience.current', { audience: audienceName })"
            :title="audienceName"
            data-testid="post-audience"
            @click="startAudience"
          >
            <component :is="audienceIcon" class="h-3 w-3" aria-hidden="true" />
          </button>
          <component :is="audienceIcon" v-else class="h-3 w-3" :aria-label="audienceName" role="img" />
          <MessageSquareOff v-if="commentPolicy === 'off'" class="h-3 w-3" :aria-label="t('post.commentsOff')" />
          <span v-if="pinned" class="ms-1 inline-flex items-center gap-0.5 rounded-full bg-brand-50 px-1.5 py-0.5 text-[10px] font-semibold text-brand-700 dark:bg-brand-950/50 dark:text-brand-300">
            <Pin class="h-3 w-3" aria-hidden="true" /> {{ t("groups.post.pinnedBadge") }}
          </span>
          <span v-if="post.approval_state === 'pending'" class="ms-1 rounded-full bg-accent-50 px-1.5 py-0.5 text-[10px] font-semibold text-accent-700 dark:bg-accent-900/40 dark:text-accent-300">
            {{ t("groups.post.pendingBadge") }}
          </span>
        </div>
      </div>

      <div class="ms-auto flex items-center gap-1">
        <div class="relative">
          <button
            class="rounded-full p-2 text-gray-500 transition hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:text-gray-400"
            :aria-label="t('profile.more')"
            :aria-expanded="menuOpen"
            aria-haspopup="true"
            data-testid="post-menu"
            @click="menuOpen = !menuOpen"
          >
            <MoreHorizontal class="h-5 w-5" />
          </button>
          <template v-if="menuOpen">
            <div class="fixed inset-0 z-40" @click="closeMenu" />
            <div
              class="popover absolute end-0 z-50 mt-1 max-h-[70vh] w-[min(20rem,calc(100vw-2rem))] overflow-y-auto p-1.5"
              :aria-label="t('postsFeed.menu.label')"
              role="group"
              data-testid="post-menu-panel"
            >
              <!-- Save -->
              <button :class="item" :aria-pressed="isSaved" data-testid="menu-save" @click="toggleSave">
                <BookmarkMinus v-if="isSaved" :class="iconCls" aria-hidden="true" />
                <Bookmark v-else :class="iconCls" aria-hidden="true" />
                <span class="min-w-0">
                  <span class="block">{{ isSaved ? t("postsFeed.menu.unsave") : t("postsFeed.menu.save") }}</span>
                  <span v-if="!isSaved" class="block text-xs font-normal text-gray-500 dark:text-gray-400">{{ t("postsFeed.menu.saveHint") }}</span>
                </span>
              </button>
              <button :class="item" data-testid="menu-collection" @click="openCollections">
                <FolderPlus :class="iconCls" aria-hidden="true" /> {{ t("postsFeed.menu.addToCollection") }}
              </button>

              <div class="my-1 border-t border-gray-100 dark:border-gray-800" />

              <!-- Author tools (a page's posts: its owners, admins and editors too) -->
              <template v-if="isAuthor || canEdit">
                <button v-if="canEdit" :class="item" data-testid="menu-edit" @click="startEdit">
                  <PenSquare :class="iconCls" aria-hidden="true" /> {{ t("postsFeed.menu.editPost") }}
                </button>
                <button v-if="canEditAudience" :class="item" data-testid="menu-audience" @click="startAudience">
                  <Users :class="iconCls" aria-hidden="true" /> {{ t("postsFeed.menu.editAudience") }}
                </button>
                <div role="group" :aria-label="t('post.commentPolicy')" class="my-1 border-y border-gray-100 py-1 dark:border-gray-800">
                  <p class="px-3 pb-0.5 pt-1 text-[11px] font-semibold text-gray-500 dark:text-gray-400">{{ t("post.commentPolicy") }}</p>
                  <button
                    v-for="p in COMMENT_POLICIES"
                    :key="p"
                    role="menuitemradio"
                    :aria-checked="commentPolicy === p"
                    class="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
                    :class="commentPolicy === p ? 'font-semibold text-brand-600 dark:text-brand-300' : ''"
                    @click="setPolicy(p)"
                  >
                    {{ t(POLICY_LABEL[p]) }}
                  </button>
                </div>
              </template>
              <button v-if="groupCanPin && post.approval_state !== 'pending'" :class="item" :disabled="pinning" @click="togglePin">
                <PinOff v-if="pinned" :class="iconCls" /><Pin v-else :class="iconCls" />
                {{ pinned ? t("groups.post.unpin") : t("groups.post.pin") }}
              </button>

              <button :class="item" data-testid="menu-copy-link" @click="copyLink">
                <Link2 :class="iconCls" aria-hidden="true" /> {{ t("postsFeed.menu.copyLink") }}
              </button>
              <button v-if="mediaIds.length" :class="item" :disabled="downloading" data-testid="menu-download" @click="downloadFromMenu">
                <Download :class="iconCls" aria-hidden="true" /> {{ t("postsFeed.media.download") }}
              </button>
              <button v-if="feedReason" :class="item" data-testid="menu-why" @click="closeMenu(); showWhy = true">
                <Info :class="iconCls" aria-hidden="true" /> {{ t("postsFeed.menu.why") }}
              </button>

              <template v-if="canHide || canSnooze || canUnfollow || canPeoplePrefs">
                <div class="my-1 border-t border-gray-100 dark:border-gray-800" />
                <button v-if="canHide" :class="item" @click="hidePost">
                  <EyeOff :class="iconCls" aria-hidden="true" /> {{ t("homeFeed.hide.action") }}
                </button>
                <button v-if="canSnooze" :class="item" data-testid="menu-snooze" @click="snoozeAuthor">
                  <Clock :class="iconCls" aria-hidden="true" />
                  <span class="min-w-0">
                    <span class="block" dir="auto">{{ t("postsFeed.menu.snooze", { name: authorDisplay }) }}</span>
                    <span class="block text-xs font-normal text-gray-500 dark:text-gray-400">{{ t("postsFeed.menu.snoozeHint") }}</span>
                  </span>
                </button>
                <button v-if="canUnfollow" :class="item" :disabled="prefBusy" data-testid="menu-unfollow" @click="unfollow">
                  <UserMinus :class="iconCls" aria-hidden="true" />
                  <span class="min-w-0">
                    <span class="block" dir="auto">{{ t("postsFeed.menu.unfollow", { name: authorDisplay }) }}</span>
                    <span class="block text-xs font-normal text-gray-500 dark:text-gray-400">{{ t("postsFeed.menu.unfollowHint") }}</span>
                  </span>
                </button>
                <template v-if="canPeoplePrefs">
                  <!-- Each item waits for its own list, so it never shows the wrong
                       state (and never re-adds someone already on the list). -->
                  <button
                    v-if="prefs.loaded('favorites')"
                    :class="item"
                    :disabled="prefBusy"
                    data-testid="menu-favorite"
                    @click="togglePref('favorites')"
                  >
                    <StarOff v-if="isFavorite" :class="iconCls" aria-hidden="true" />
                    <Star v-else :class="iconCls" aria-hidden="true" />
                    <span class="min-w-0">
                      <span class="block" dir="auto">{{ t(isFavorite ? "postsFeed.menu.unfavorite" : "postsFeed.menu.favorite", { name: authorDisplay }) }}</span>
                      <span v-if="!isFavorite" class="block text-xs font-normal text-gray-500 dark:text-gray-400">{{ t("postsFeed.menu.favoriteHint") }}</span>
                    </span>
                  </button>
                  <button
                    v-if="prefs.loaded('mutes')"
                    :class="item"
                    :disabled="prefBusy"
                    data-testid="menu-mute"
                    @click="togglePref('mutes')"
                  >
                    <BellOff :class="iconCls" aria-hidden="true" />
                    <span class="min-w-0">
                      <span class="block" dir="auto">{{ t(isMuted ? "postsFeed.menu.unmute" : "postsFeed.menu.mute", { name: authorDisplay }) }}</span>
                      <span v-if="!isMuted" class="block text-xs font-normal text-gray-500 dark:text-gray-400">{{ t("postsFeed.menu.muteHint") }}</span>
                    </span>
                  </button>
                  <button
                    v-if="prefs.loaded('blocks')"
                    :class="[item, 'text-red-600 dark:text-red-400']"
                    :disabled="prefBusy"
                    data-testid="menu-block"
                    @click="closeMenu(); confirmBlock = true"
                  >
                    <Ban :class="iconCls" aria-hidden="true" />
                    <span class="min-w-0">
                      <span class="block" dir="auto">{{ t("postsFeed.menu.block", { name: authorDisplay }) }}</span>
                      <span class="block text-xs font-normal text-gray-500 dark:text-gray-400">{{ t("postsFeed.menu.blockHint") }}</span>
                    </span>
                  </button>
                </template>
              </template>

              <template v-if="canRemove || !isAuthor">
                <div class="my-1 border-t border-gray-100 dark:border-gray-800" />
                <button v-if="!isAuthor" :class="item" @click="closeMenu(); showReport = true">
                  <Flag :class="iconCls" aria-hidden="true" /> {{ t("post.report") }}
                </button>
                <button
                  v-if="canRemove"
                  :class="[item, 'text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40']"
                  :disabled="removing"
                  @click="remove"
                >
                  <Trash2 class="h-5 w-5 shrink-0" aria-hidden="true" /> {{ t("friends.delete") }}
                </button>
              </template>
            </div>
          </template>
        </div>

        <button
          v-if="canHide"
          class="rounded-full p-2 text-gray-500 transition hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:text-gray-400"
          :aria-label="t('homeFeed.hide.action')"
          :title="t('homeFeed.hide.action')"
          data-testid="hide-post"
          @click="hidePost"
        >
          <X class="h-5 w-5" aria-hidden="true" />
        </button>
      </div>
    </header>

    <p v-if="localBody" class="mt-3 whitespace-pre-wrap break-words text-[15px] leading-relaxed" dir="auto">
      <RichText :body="localBody" />
      <span v-if="edited" class="text-xs text-gray-500 dark:text-gray-400">· {{ t("messages.edited") }}</span>
    </p>

    <LinkPreviewCard v-if="linkPreview" :preview="linkPreview" />
    <PollCard v-if="post.poll" :post-id="post.id" :poll="post.poll" />
    <SharedPostCard v-if="isShare" :post="post.shared_post" :view-key="post.id" />

    <ConfirmActionDialog
      v-if="confirmBlock"
      :title="t('people.actions.blockTitle', { name: authorDisplay })"
      :hint="t('people.actions.blockHint')"
      :confirm-label="t('people.actions.block')"
      :busy="prefBusy"
      @confirm="blockAuthor"
      @cancel="confirmBlock = false"
    />

    <!-- Report box -->
    <div v-if="showReport" class="mt-3 rounded-xl border border-gray-200 p-3 dark:border-gray-800">
      <p class="mb-2 text-sm font-medium">{{ t("post.reportReason") }}</p>
      <textarea v-model="reportReason" class="input min-h-16" rows="2" dir="auto" :aria-label="t('post.reportReason')" />
      <div class="mt-2 flex justify-end gap-2">
        <button class="btn-ghost" @click="showReport = false">{{ t("feed.cancel") }}</button>
        <button class="btn-primary" :disabled="!reportReason.trim()" @click="submitReport">{{ t("post.report") }}</button>
      </div>
    </div>
    <p v-if="reported" class="mt-2 text-xs font-medium text-green-600">{{ t("post.reportSent") }}</p>

    <!-- Media run edge to edge, as on the reference. -->
    <div v-if="mediaIds.length" class="-mx-4 sm:-mx-5">
      <!-- A video post (5.7): one transcoded video, played through the media service's token-checked HLS. -->
      <VideoPlayer
        v-if="post.type === 'video' || post.type === 'reel'"
        :media-id="mediaIds[0]"
        :signal-item="videoItem"
        :signal-surface="signalSurface"
        class="!rounded-none"
      />
      <!-- A reel (5.8) in the feed: played here, and one tap away from the reels viewer. -->
      <RouterLink
        v-if="post.type === 'reel'"
        :to="{ name: 'reel', params: { id: post.id } }"
        class="mx-4 mt-2 inline-flex items-center gap-1.5 text-sm font-semibold text-brand-600 hover:underline sm:mx-5 dark:text-brand-300"
        data-testid="post-watch-reel"
      >
        {{ t("reels.watchInReels") }}
      </RouterLink>
      <MediaGrid v-if="post.type !== 'video' && post.type !== 'reel'" :media-ids="mediaIds" :author-name="authorDisplay" compact @open="viewer.open" />
    </div>
    <MediaTheater
      v-if="viewer.index.value !== null"
      :media-ids="mediaIds"
      :index="viewer.index.value"
      :author-name="authorDisplay"
      @go="viewer.go"
      @close="viewer.close"
    >
      <!-- The post beside its photos (plan 08): same counts as this card. -->
      <template #panel>
        <PostTheaterPanel
          :post="current"
          :author-name="authorDisplay"
          :author-avatar="avatarId"
          :author-to="authorTo"
          :body="localBody"
          :policy="commentPolicy"
          :known-names="knownNames"
          :can-moderate="groupModerator"
          :state="{ myReaction, reactionCount, reactionCounts, commentCount }"
          @changed="onPanelChanged"
          @share="shareFromTheater"
        />
      </template>
    </MediaTheater>

    <div class="mt-3">
      <PostActions
        :my-reaction="myReaction"
        :reaction-count="reactionCount"
        :reaction-counts="reactionCounts"
        :comment-count="commentCount"
        :share-count="shareCount"
        @react="onReact"
        @unreact="onUnreact"
        @comment="toggleComments"
        @share="sharing = !sharing"
        @reactions="showReactions = true"
        @shares="showShares = true"
      />
    </div>
    <ShareBox v-if="sharing" :post="post" @cancel="sharing = false" @shared="onShared" />

    <section
      v-if="!showComments && (previewComments.length || commentPolicy !== 'off')"
      class="mt-2 space-y-2 border-t border-gray-100 pt-3 dark:border-gray-800"
      :aria-label="previewComments.length ? t('homeFeed.comments.preview') : undefined"
      data-testid="comment-preview"
    >
      <button
        v-if="previewComments.length && moreToView"
        type="button"
        class="text-sm font-semibold text-gray-600 hover:underline dark:text-gray-300"
        @click="toggleComments"
      >
        {{ t("post.moreComments") }}
      </button>
      <CommentItem
        v-for="c in previewComments"
        :key="c.id"
        :comment="c"
        :name="previewName(c.author_id)"
        :can-edit="c.author_id === auth.account?.id"
        :can-delete="c.author_id === auth.account?.id || isAuthor || groupModerator"
        :can-reply="commentPolicy !== 'off'"
        :busy="previewBusyId === c.id"
        :reported="previewReported.has(c.id)"
        @reply="toggleComments"
        @edit="editPreview(c, $event)"
        @remove="removePreview(c)"
        @react="reactPreview(c, $event)"
        @report="reportPreview(c, $event)"
      />
      <CommentInput v-if="commentPolicy !== 'off'" :submitting="inlineSubmitting" @submit="submitInline" />
    </section>

    <section
      v-if="commentsMounted"
      v-show="showComments"
      class="mt-3 border-t border-gray-100 pt-3 dark:border-gray-800"
    >
      <CommentList
        :post-id="post.id"
        :post-author-id="post.author_id"
        :policy="commentPolicy"
        :known-names="knownNames"
        :focus-id="focusCommentId"
        :focus-root-id="focusThreadId"
        :can-moderate="groupModerator"
        @added="commentCount += 1"
        @total="commentCount = $event"
        @edited="replacePreview"
        @removed="dropPreview"
      />
    </section>

    <ReactionsDialog
      v-if="showReactions"
      :post-id="post.id"
      :counts="reactionCounts"
      :total="reactionCount"
      @close="showReactions = false"
    />
    <SharesDialog v-if="showShares" :post-id="post.id" @close="showShares = false" />
    <ComposerDialog v-if="editing" :post="current" @close="editing = false" @updated="onEdited" />
    <AudienceDialog
      v-if="editingAudience"
      :post-id="post.id"
      :audience="current.audience"
      :is-share="isShare"
      @close="editingAudience = false"
      @updated="onAudience"
    />
    <WhyThisPost
      v-if="showWhy && feedReason"
      :reason="feedReason"
      :name="authorDisplay"
      :page="!isUserAuthor"
      :mode="feedMode"
      @close="showWhy = false"
    />
    <SaveToCollection v-if="savingTo" :post-id="post.id" @close="savingTo = false" @done="isSaved = true" />
  </article>
</template>
