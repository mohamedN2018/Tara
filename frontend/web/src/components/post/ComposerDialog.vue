<script setup lang="ts">
import {
  ArrowLeft,
  BarChart3,
  CalendarClock,
  Check,
  ChevronDown,
  FileText,
  Film,
  Globe,
  Image as ImageIcon,
  ImagePlus,
  Lock,
  MapPin,
  Plus,
  Smile,
  Trash2,
  UserCheck,
  UserPlus,
  Users,
  X,
} from "lucide-vue-next";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { foldText } from "@/components/layout/menuCatalog";
import VideoComposerAttachment from "@/components/media/VideoComposerAttachment.vue";
import MentionField from "@/components/post/MentionField.vue";
import { errorMessage } from "@/lib/errors";
import { IMAGE_ACCEPT, isHeic } from "@/lib/heic";
import { relativeTime } from "@/lib/format";
import { useFocusTrap } from "@/lib/useFocusTrap";
import {
  ACTIVITIES,
  COMPOSER_ERRORS,
  type ComposerPost,
  composerService,
  FEELING_EMOJI,
  FEELINGS,
  fromLocalInput,
  LOCATION_MAX,
  MAX_TAGS,
  scheduleBounds,
  scheduleProblem,
  timeZoneName,
  toLocalInput,
} from "@/services/composer";
import { graphService } from "@/services/graph";
import { mediaService } from "@/services/media";
import { COMMENT_POLICIES, type CommentPolicy, postService } from "@/services/post";
import type { VideoAttachmentState } from "@/services/video";
import { profileService, type UserCard } from "@/services/profile";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";
import type { Post } from "@/types";

/**
 * One composer for every post (plan 08, 2C): audience, text with mentions and
 * hashtags, photos, a poll, people tags, a feeling or activity, a location, a
 * schedule (in the viewer's own time zone), "Save draft", and the author's
 * "Drafts & scheduled" list. In a group (`groupId`) the server forces the
 * group's audience, and drafts and scheduling are not offered.
 */
type Start = "photo" | "poll" | "feeling" | "drafts" | null;
type View = "main" | "audience" | "tag" | "feeling" | "schedule" | "drafts";

const props = withDefaults(
  defineProps<{
    groupId?: string | null;
    groupName?: string;
    /** A draft or scheduled post to edit. */
    draft?: ComposerPost | null;
    start?: Start;
    /** Photos picked before the dialog opened (the card's quick action). */
    files?: File[];
    /** A new post pre-scheduled at this instant (the studio planner's "Schedule a post"). */
    scheduleAt?: string | null;
    /**
     * A published post to edit (T4): text, audience, tags, feeling, location and
     * comment policy. Photos, video, poll, schedule and drafts are not offered.
     */
    post?: Post | null;
  }>(),
  { groupId: null, groupName: "", draft: null, start: null, files: () => [], scheduleAt: null, post: null },
);
const emit = defineEmits<{
  close: [];
  /** Published now: show it in the feed. */
  published: [post: Post];
  /** Kept as a draft or scheduled: only the author's drafts list shows it. */
  saved: [post: ComposerPost];
  /** A published post was edited (`post` mode). */
  updated: [post: Post];
}>();

const { t, locale } = useI18n();
const auth = useAuthStore();
const directory = useDirectoryStore();
const toasts = useToastStore();

const view = ref<View>(props.start === "drafts" && !props.groupId ? "drafts" : props.start === "feeling" ? "feeling" : "main");
const editing = ref<ComposerPost | null>(props.draft);
// Editing a published post: only what PATCH /posts/<id>/ changes.
const published = computed(() => props.post);
const inGroup = computed(() => !!props.groupId || !!props.post?.group_id);
const canDraft = computed(() => !props.groupId && !props.post);

// ---- the post itself -----------------------------------------------------------
const body = ref("");
const audience = ref("public");
const commentPolicy = ref<CommentPolicy>("everyone");
const mediaIds = ref<string[]>([]);
const previews = ref<(string | null)[]>([]);
const uploading = ref(false);
const submitting = ref(false);
const error = ref("");
const taggedIds = ref<string[]>([]);
const feeling = ref("");
const location = ref("");
const locationOpen = ref(false);
const scheduleValue = ref("");
const MAX_PHOTOS = 10;
// One video instead of photos (video pipeline, 5.2): posted once media says it is ready.
const videoId = ref<string | null>(null);
const videoState = ref<VideoAttachmentState>("idle");
// Uploading counts too: the video is not in `videoId` yet, but it will be.
const videoUploading = computed(() => videoState.value === "uploading");
const videoBusy = computed(() => videoUploading.value || (!!videoId.value && videoState.value !== "ready"));
const hasVideo = computed(() => !!videoId.value || videoUploading.value);
// Remounts the attachment, so a video picked before opening a draft (even one
// still uploading) cannot come back into the draft, which has no video field.
const videoKey = ref(0);
const videoPicker = ref<InstanceType<typeof VideoComposerAttachment> | null>(null);

const POLICY_LABEL: Record<CommentPolicy, string> = {
  everyone: "post.commentPolicyEveryone",
  friends: "post.commentPolicyFriends",
  off: "post.commentPolicyOff",
};
const AUDIENCES = [
  { v: "public", icon: Globe, label: "feed.audiencePublic" },
  { v: "friends", icon: Users, label: "feed.audienceFriends" },
  { v: "followers", icon: UserCheck, label: "feed.audienceFollowers" },
  { v: "only_me", icon: Lock, label: "feed.audienceOnlyMe" },
];
const currentAudience = computed(() => AUDIENCES.find((a) => a.v === audience.value) ?? AUDIENCES[0]);

// Poll: the post body is the question (new posts only).
const POLL_MAX_OPTIONS = 6;
const pollOpen = ref(props.start === "poll");
const pollOptions = ref(["", ""]);
const pollHours = ref<number | null>(null);
const POLL_DURATIONS = [
  { hours: null, label: "feed.pollNoEnd" },
  { hours: 24, label: "feed.pollDay" },
  { hours: 72, label: "feed.pollThreeDays" },
  { hours: 168, label: "feed.pollWeek" },
];
const filledOptions = computed(() => pollOptions.value.map((o) => o.trim()).filter(Boolean));
const pollReady = computed(() => filledOptions.value.length >= 2 && !!body.value.trim());

const authorName = () => auth.profile?.display_name || auth.account?.email?.split("@")[0] || "?";
const placeholder = computed(() =>
  pollOpen.value ? t("feed.pollQuestion") : props.groupId ? t("groups.composer.placeholder") : t("feed.composerPlaceholder"),
);
const hasContent = computed(
  () =>
    !!body.value.trim() ||
    mediaIds.value.length > 0 ||
    !!videoId.value ||
    !!feeling.value ||
    (editing.value?.media_ids.length ?? 0) > 0 ||
    (published.value?.media_ids.length ?? 0) > 0 ||
    !!published.value?.shared_post_id,
);
const scheduledIso = computed(() => (scheduleValue.value ? fromLocalInput(scheduleValue.value) : null));
const fmtTime = (iso: string) =>
  new Date(iso).toLocaleString(locale.value === "ar" ? "ar-EG" : "en-GB", { dateStyle: "medium", timeStyle: "short" });

function load(draft: ComposerPost) {
  editing.value = draft;
  body.value = draft.body;
  audience.value = draft.audience;
  commentPolicy.value = draft.comment_policy ?? "everyone";
  taggedIds.value = [...(draft.tagged_ids ?? [])];
  feeling.value = draft.feeling ?? "";
  location.value = draft.location ?? "";
  locationOpen.value = !!location.value;
  scheduleValue.value = draft.publish_at ? toLocalInput(new Date(draft.publish_at)) : "";
  previews.value.forEach(revoke);
  mediaIds.value = [];
  previews.value = [];
  videoId.value = null;
  videoState.value = "idle";
  videoKey.value++;
  pollOpen.value = false;
  error.value = "";
  view.value = "main";
}

// ---- photos ----------------------------------------------------------------------
async function upload(files: File[]) {
  // A post carries photos or one video, never both.
  if (!files.length || hasVideo.value) return;
  const room = MAX_PHOTOS - mediaIds.value.length;
  uploading.value = true;
  error.value = room < files.length ? t("feed.tooManyPhotos", { max: MAX_PHOTOS }) : "";
  try {
    for (const file of files.slice(0, Math.max(0, room))) {
      const asset = await mediaService.upload(file, "image");
      mediaIds.value.push(asset.id);
      previews.value.push(isHeic(file) ? null : URL.createObjectURL(file));
    }
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    uploading.value = false;
  }
}

function onFiles(e: Event) {
  const input = e.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  input.value = ""; // picking the same file again still fires `change`
  void upload(files);
}

function revoke(url: string | null) {
  if (url) URL.revokeObjectURL(url);
}

function removeMedia(i: number) {
  revoke(previews.value[i]);
  mediaIds.value.splice(i, 1);
  previews.value.splice(i, 1);
}

onBeforeUnmount(() => previews.value.forEach(revoke));

// ---- tag people (friends) ----------------------------------------------------------
const friendQuery = ref("");
const friends = ref<UserCard[] | null>(null);
const friendsLoading = ref(false);

async function loadFriends() {
  if (friends.value || friendsLoading.value) return;
  friendsLoading.value = true;
  try {
    const ids = await graphService.friends();
    const cards: UserCard[] = [];
    for (let i = 0; i < ids.length; i += 100) cards.push(...(await profileService.lookup(ids.slice(i, i + 100))));
    cards.forEach((c) => directory.remember(c.account_id, c.display_name || c.handle, c.avatar_media_id, c.handle));
    friends.value = cards;
  } catch (err) {
    friends.value = [];
    error.value = errorMessage(err);
  } finally {
    friendsLoading.value = false;
  }
}

const shownFriends = computed(() => {
  const q = foldText(friendQuery.value);
  const list = friends.value ?? [];
  return q ? list.filter((f) => foldText(`${f.display_name} ${f.handle}`).includes(q)) : list;
});

function toggleTag(id: string) {
  const i = taggedIds.value.indexOf(id);
  if (i >= 0) taggedIds.value.splice(i, 1);
  else if (taggedIds.value.length < MAX_TAGS) taggedIds.value.push(id);
}

// ---- feeling / activity -----------------------------------------------------------
const feelingTab = ref<"feelings" | "activities">("feelings");
const feelingKeys = computed<readonly string[]>(() => (feelingTab.value === "feelings" ? FEELINGS : ACTIVITIES));

function pickFeeling(key: string) {
  feeling.value = feeling.value === key ? "" : key;
  view.value = "main";
}

// ---- schedule -----------------------------------------------------------------------
const bounds = ref(scheduleBounds());
const zone = timeZoneName();
const schedulePick = ref("");

function openSchedule() {
  bounds.value = scheduleBounds();
  schedulePick.value = scheduleValue.value || bounds.value.min;
  view.value = "schedule";
}

const scheduleError = computed(() => {
  if (!schedulePick.value) return "";
  const problem = scheduleProblem(schedulePick.value);
  if (problem === "past") return t("composer.errors.publishAtPast");
  if (problem === "far") return t("composer.errors.publishAtTooFar");
  return "";
});

function confirmSchedule() {
  if (scheduleError.value || !schedulePick.value) return;
  scheduleValue.value = schedulePick.value;
  view.value = "main";
}

function clearSchedule() {
  scheduleValue.value = "";
  view.value = "main";
}

// ---- drafts & scheduled ---------------------------------------------------------------
const drafts = ref<ComposerPost[]>([]);
const draftsCursor = ref<string | null>(null);
const draftsLoading = ref(false);
const confirmingDelete = ref<string | null>(null);

async function loadDrafts(reset = true) {
  if (draftsLoading.value) return;
  draftsLoading.value = true;
  try {
    const page = await composerService.drafts(undefined, reset ? null : draftsCursor.value);
    drafts.value = reset ? page.data : drafts.value.concat(page.data);
    draftsCursor.value = page.page.has_more ? page.page.next_cursor : null;
  } catch (err) {
    toasts.error(err);
  } finally {
    draftsLoading.value = false;
  }
}

async function publishFromList(d: ComposerPost) {
  try {
    const post = await composerService.publishDraft(d.id);
    drafts.value = drafts.value.filter((x) => x.id !== d.id);
    toasts.success(t("composer.publishedToast"));
    emit("published", post);
  } catch (err) {
    toasts.error(err, COMPOSER_ERRORS);
    void loadDrafts();
  }
}

async function deleteFromList(d: ComposerPost) {
  try {
    await composerService.deleteDraft(d.id);
    drafts.value = drafts.value.filter((x) => x.id !== d.id);
    confirmingDelete.value = null;
    if (editing.value?.id === d.id) reset();
    toasts.success(t("composer.deletedDraft"));
  } catch (err) {
    toasts.error(err);
  }
}

watch(view, (v) => {
  if (v === "drafts") void loadDrafts();
  if (v === "tag") void loadFriends();
});

// ---- submit -------------------------------------------------------------------------
function reset() {
  editing.value = null;
  body.value = "";
  previews.value.forEach(revoke);
  mediaIds.value = [];
  previews.value = [];
  videoId.value = null;
  videoState.value = "idle";
  audience.value = "public";
  commentPolicy.value = "everyone";
  taggedIds.value = [];
  feeling.value = "";
  location.value = "";
  locationOpen.value = false;
  scheduleValue.value = "";
  pollOpen.value = false;
  pollOptions.value = ["", ""];
  pollHours.value = null;
  error.value = "";
}

function fields() {
  return {
    body: body.value.trim(),
    comment_policy: commentPolicy.value,
    tagged_ids: [...taggedIds.value],
    location: location.value.trim(),
    feeling: feeling.value,
    ...(inGroup.value ? {} : { audience: audience.value }),
  };
}

async function saveEdit() {
  const target = published.value;
  if (!target || submitting.value || !hasContent.value) return;
  submitting.value = true;
  error.value = "";
  try {
    const updated = await postService.update(target.id, fields());
    toasts.success(t("postsFeed.edit.saved"));
    emit("updated", updated);
    emit("close");
  } catch (err) {
    error.value = errorMessage(err, COMPOSER_ERRORS);
  } finally {
    submitting.value = false;
  }
}

/** `publish`: now, or at the picked time. `draft`: keep it for later. */
async function submit(mode: "publish" | "draft") {
  if (submitting.value || uploading.value || videoBusy.value) return;
  if (!hasContent.value) return;
  // Never drop shown photos without a word: the post takes one or the other.
  if (videoId.value && mediaIds.value.length) {
    error.value = t("composer.errors.photosOrVideo");
    return;
  }
  if (pollOpen.value && !pollReady.value) {
    error.value = t("feed.pollIncomplete");
    return;
  }
  const at = mode === "publish" ? scheduledIso.value : null;
  if (mode === "publish" && scheduleValue.value) {
    const problem = scheduleProblem(scheduleValue.value);
    if (problem) {
      error.value = t(problem === "past" ? "composer.errors.publishAtPast" : "composer.errors.publishAtTooFar");
      return;
    }
  }
  submitting.value = true;
  error.value = "";
  try {
    let post: ComposerPost;
    if (editing.value) {
      post = await composerService.editDraft(editing.value.id, { ...fields(), publish_at: at });
      if (mode === "publish" && !at) post = await composerService.publishDraft(post.id);
    } else {
      post = await composerService.create({
        ...fields(),
        ...(videoId.value ? { media_ids: [videoId.value], type: "video" as const } : { media_ids: mediaIds.value }),
        ...(props.groupId ? { group_id: props.groupId } : {}),
        ...(pollOpen.value ? { poll: { options: filledOptions.value, duration_hours: pollHours.value } } : {}),
        ...(mode === "draft" ? { draft: true } : at ? { publish_at: at } : {}),
      });
    }
    if (post.state === "draft") {
      toasts.success(t("composer.savedDraft"));
      emit("saved", post);
    } else if (post.state === "scheduled") {
      toasts.success(t("composer.scheduledToast", { time: fmtTime(post.publish_at ?? at ?? "") }));
      emit("saved", post);
    } else {
      emit("published", post);
    }
    reset();
    emit("close");
  } catch (err) {
    error.value = errorMessage(err, COMPOSER_ERRORS);
  } finally {
    submitting.value = false;
  }
}

const primaryLabel = computed(() => {
  if (published.value) return submitting.value ? t("postsFeed.edit.saving") : t("postsFeed.edit.save");
  if (submitting.value) return t("feed.posting");
  return scheduleValue.value ? t("composer.schedulePost") : t("feed.post");
});

// ---- dialog plumbing ------------------------------------------------------------------
const panel = ref<HTMLElement | null>(null);
const editor = ref<InstanceType<typeof MentionField> | null>(null);
useFocusTrap(panel);
// Escape steps back from a sub-view, then closes. An Escape the mention list
// already used (it closes its suggestions) is left alone.
function onEscape(e: KeyboardEvent) {
  if (e.key !== "Escape" || e.defaultPrevented) return;
  e.preventDefault();
  if (view.value !== "main") view.value = "main";
  else emit("close");
}

const viewTitle = computed(() => {
  switch (view.value) {
    case "audience":
      return t("feed.audience");
    case "tag":
      return t("composer.tagPeople");
    case "feeling":
      return t("composer.feelingTabs");
    case "schedule":
      return t("composer.scheduleTitle");
    case "drafts":
      return t("composer.draftsAndScheduled");
    default:
      if (published.value) return t("postsFeed.edit.title");
      return editing.value ? t("composer.editDraftTitle") : t("composer.title");
  }
});

watch(view, async (v) => {
  if (v !== "main") return;
  await nextTick();
  editor.value?.focus();
});

// On the window: a sub-view can take focus away from the panel (hidden buttons).
onMounted(() => window.addEventListener("keydown", onEscape));
onBeforeUnmount(() => window.removeEventListener("keydown", onEscape));

watch(view, async (v) => {
  if (v === "main") return;
  await nextTick();
  panel.value?.querySelector<HTMLElement>("[data-view] input, [data-view] button")?.focus();
});

onMounted(async () => {
  if (props.draft) load(props.draft);
  if (props.post) {
    const p = props.post as Post & Partial<ComposerPost>;
    body.value = p.body ?? "";
    audience.value = p.audience === "group" ? "public" : p.audience;
    commentPolicy.value = p.comment_policy ?? "everyone";
    taggedIds.value = [...(p.tagged_ids ?? [])];
    feeling.value = p.feeling ?? "";
    location.value = p.location ?? "";
    locationOpen.value = !!location.value;
  }
  if (props.files.length) void upload(props.files);
  if (props.scheduleAt && !props.draft && canDraft.value) scheduleValue.value = toLocalInput(new Date(props.scheduleAt));
  if (view.value === "drafts") void loadDrafts();
  await nextTick();
  if (view.value === "main") editor.value?.focus();
});

const taggedNames = computed(() => taggedIds.value.map((id) => directory.label(id)));
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 backdrop-blur-sm sm:items-center sm:p-4" data-testid="composer-dialog">
      <div class="fixed inset-0" aria-hidden="true" @click="emit('close')" />
      <div
        ref="panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="composer-title"
        tabindex="-1"
        class="card relative z-10 flex max-h-[92dvh] w-full animate-pop-in flex-col rounded-b-none rounded-t-2xl p-0 shadow-pop sm:max-w-lg sm:rounded-2xl"
      >
        <!-- Header: back (sub-views) · title · close -->
        <div class="relative flex items-center justify-center border-b border-gray-100 px-12 py-3 dark:border-gray-800">
          <button
            v-if="view !== 'main'"
            type="button"
            class="icon-btn absolute start-2 top-1/2 -translate-y-1/2"
            :aria-label="t('composer.back')"
            data-testid="composer-back"
            @click="view = 'main'"
          >
            <ArrowLeft class="h-5 w-5 rtl:-scale-x-100" aria-hidden="true" />
          </button>
          <h2 id="composer-title" class="truncate text-lg font-bold">{{ viewTitle }}</h2>
          <button type="button" class="icon-btn absolute end-2 top-1/2 -translate-y-1/2" :aria-label="t('composer.close')" @click="emit('close')">
            <X class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <!-- ================= main ================= -->
        <div v-show="view === 'main'" class="min-h-0 flex-1 overflow-y-auto px-4 pb-4 pt-3">
          <div class="flex items-center gap-3">
            <UserAvatar :name="authorName()" :media-id="auth.profile?.avatar_media_id" :size="40" />
            <div class="min-w-0">
              <p class="text-sm font-semibold" dir="auto" data-testid="composer-summary">
                <span>{{ authorName() }}</span>
                <span v-if="feeling" class="font-normal text-gray-600 dark:text-gray-300">
                  — <span aria-hidden="true">{{ FEELING_EMOJI[feeling] }}</span> {{ t(`composer.feelings.${feeling}`) }}</span>
                <span v-if="taggedNames.length" class="font-normal text-gray-600 dark:text-gray-300">
                  {{ " " }}{{
                    taggedNames.length > 1
                      ? t("composer.meta.withOthers", { name: taggedNames[0], count: taggedNames.length - 1 }, taggedNames.length - 1)
                      : t("composer.meta.with", { name: taggedNames[0] })
                  }}</span>
                <span v-if="location.trim()" class="font-normal text-gray-600 dark:text-gray-300">
                  {{ " " }}{{ t("composer.meta.at", { place: location.trim() }) }}</span>
              </p>
              <p
                v-if="inGroup"
                class="mt-0.5 inline-flex items-center gap-1 rounded-md bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700 dark:bg-brand-950/50 dark:text-brand-300"
              >
                <Users class="h-3 w-3" aria-hidden="true" />
                <span v-if="groupName" dir="auto">{{ t("groups.composer.target", { name: groupName }) }}</span>
                <span v-else>{{ t("feed.audienceGroup") }}</span>
              </p>
              <button
                v-else
                type="button"
                class="mt-0.5 inline-flex items-center gap-1 rounded-md bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700 transition hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-200"
                :aria-label="`${t('feed.audience')}: ${t(currentAudience.label)}`"
                data-testid="composer-audience"
                @click="view = 'audience'"
              >
                <component :is="currentAudience.icon" class="h-3 w-3" aria-hidden="true" />
                {{ t(currentAudience.label) }}
                <ChevronDown class="h-3 w-3" aria-hidden="true" />
              </button>
            </div>
          </div>

          <MentionField
            ref="editor"
            v-model="body"
            multiline
            class="mt-3"
            field-class="input min-h-[120px] resize-none border-0 bg-transparent px-0 text-lg focus:ring-0 dark:bg-transparent"
            :placeholder="placeholder"
          />

          <div v-if="pollOpen" class="mt-2 space-y-2" data-testid="poll-editor">
            <input
              v-for="(_, i) in pollOptions"
              :key="i"
              v-model="pollOptions[i]"
              class="input"
              dir="auto"
              maxlength="120"
              :placeholder="t('feed.pollOption', { n: i + 1 })"
              :aria-label="t('feed.pollOption', { n: i + 1 })"
            />
            <div class="flex items-center justify-between gap-2">
              <button v-if="pollOptions.length < POLL_MAX_OPTIONS" type="button" class="btn-ghost text-sm" @click="pollOptions.push('')">
                <Plus class="h-4 w-4" aria-hidden="true" /> {{ t("feed.pollAddOption") }}
              </button>
              <select v-model="pollHours" class="input ms-auto w-auto" :aria-label="t('feed.pollDuration')">
                <option v-for="d in POLL_DURATIONS" :key="d.label" :value="d.hours">{{ t(d.label) }}</option>
              </select>
            </div>
          </div>

          <div v-if="locationOpen" class="mt-2 flex items-center gap-2">
            <MapPin class="h-4 w-4 shrink-0 text-accent-600 dark:text-accent-300" aria-hidden="true" />
            <input
              v-model="location"
              class="input h-9"
              dir="auto"
              :maxlength="LOCATION_MAX"
              :placeholder="t('composer.locationPlaceholder')"
              :aria-label="t('composer.location')"
              data-testid="composer-location"
            />
          </div>

          <!-- A draft's photos (read-only), or this post's new photos -->
          <div v-if="editing && editing.media_ids.length" class="mt-2">
            <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("composer.photosFixed") }}</p>
          </div>
          <div v-if="previews.length" class="mt-2 grid grid-cols-4 gap-2 sm:grid-cols-5">
            <div v-for="(src, i) in previews" :key="i" class="relative">
              <img v-if="src" :src="src" class="h-20 w-full rounded-lg object-cover" :alt="t('post.imageAlt', { n: i + 1, name: authorName() })" />
              <div
                v-else
                role="img"
                class="flex h-20 w-full flex-col items-center justify-center gap-1 rounded-lg bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400"
                :aria-label="t('feed.heicPreview', { n: i + 1 })"
                data-testid="heic-placeholder"
              >
                <ImageIcon class="h-5 w-5" aria-hidden="true" />
                <span class="text-[10px] font-semibold">HEIC</span>
              </div>
              <button class="absolute end-1 top-1 rounded-full bg-black/60 p-0.5 text-white" :aria-label="t('friends.delete')" @click="removeMedia(i)">
                <X class="h-3 w-3" aria-hidden="true" />
              </button>
            </div>
          </div>

          <p v-if="published && (published.media_ids.length || published.shared_post_id)" class="mt-2 text-xs text-gray-500 dark:text-gray-400">
            {{ t("composer.photosFixed") }}
          </p>

          <!-- One video instead of photos: uploaded, processed, then previewed (video pipeline). -->
          <VideoComposerAttachment v-if="!published" :key="videoKey" ref="videoPicker" v-model:media-id="videoId" :show-button="false" @state="videoState = $event" />

          <p
            v-if="scheduledIso"
            class="mt-3 flex items-center gap-2 rounded-xl bg-brand-50 px-3 py-2 text-sm text-brand-800 dark:bg-brand-950/50 dark:text-brand-200"
            data-testid="composer-schedule-summary"
          >
            <CalendarClock class="h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{{ t("composer.scheduledFor", { time: fmtTime(scheduledIso) }) }}</span>
          </p>

          <!-- Add to your post -->
          <div class="mt-3 flex flex-wrap items-center gap-1 rounded-xl border border-gray-200 p-2 dark:border-gray-700" role="group" :aria-label="t('composer.addToPost')">
            <span class="me-auto px-1 text-sm font-semibold">{{ t("composer.addToPost") }}</span>
            <label
              v-if="!editing && !published && !hasVideo"
              class="icon-btn cursor-pointer focus-within:ring-2 focus-within:ring-brand-400"
              :class="uploading ? 'opacity-50' : ''"
              :title="t('feed.addPhotos')"
            >
              <ImagePlus class="h-5 w-5 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
              <input type="file" :accept="IMAGE_ACCEPT" multiple class="sr-only" :aria-label="t('feed.addPhotos')" @change="onFiles" />
            </label>
            <button
              v-if="!editing && !published"
              type="button"
              class="icon-btn"
              :title="t('video.composer.addLabel')"
              :aria-label="t('video.composer.addLabel')"
              :disabled="uploading || mediaIds.length > 0 || !!videoId || pollOpen"
              data-testid="composer-video"
              @click="videoPicker?.pick()"
            >
              <Film class="h-5 w-5 text-accent-500" aria-hidden="true" />
            </button>
            <button type="button" class="icon-btn" :title="t('composer.tagPeople')" :aria-label="t('composer.tagPeople')" data-testid="composer-tag" @click="view = 'tag'">
              <UserPlus class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" />
            </button>
            <button type="button" class="icon-btn" :title="t('composer.feeling')" :aria-label="t('composer.feeling')" data-testid="composer-feeling" @click="view = 'feeling'">
              <Smile class="h-5 w-5 text-amber-500" aria-hidden="true" />
            </button>
            <button
              type="button"
              class="icon-btn"
              :title="t('composer.location')"
              :aria-label="t('composer.location')"
              :aria-pressed="locationOpen"
              data-testid="composer-location-toggle"
              @click="locationOpen = !locationOpen"
            >
              <MapPin class="h-5 w-5 text-accent-600 dark:text-accent-300" aria-hidden="true" />
            </button>
            <button
              v-if="!editing && !published"
              type="button"
              class="icon-btn"
              :title="t('feed.poll')"
              :aria-label="t('feed.poll')"
              :aria-pressed="pollOpen"
              @click="pollOpen = !pollOpen"
            >
              <BarChart3 class="h-5 w-5 text-sky-600 dark:text-sky-400" aria-hidden="true" />
            </button>
            <button
              v-if="canDraft"
              type="button"
              class="icon-btn"
              :title="t('composer.schedule')"
              :aria-label="t('composer.schedule')"
              data-testid="composer-schedule"
              @click="openSchedule"
            >
              <CalendarClock class="h-5 w-5 text-brand-500 dark:text-brand-300" aria-hidden="true" />
            </button>
          </div>

          <div class="mt-3 flex flex-wrap items-center gap-2">
            <select v-model="commentPolicy" class="input h-9 w-auto py-1 text-xs" :aria-label="t('post.commentPolicy')" data-testid="comment-policy">
              <option v-for="p in COMMENT_POLICIES" :key="p" :value="p">{{ t(POLICY_LABEL[p]) }}</option>
            </select>
            <button v-if="canDraft" type="button" class="btn-ghost text-sm" data-testid="composer-drafts" @click="view = 'drafts'">
              <FileText class="h-4 w-4" aria-hidden="true" /> {{ t("composer.draftsAndScheduled") }}
            </button>
          </div>

          <p v-if="error" class="mt-2 text-sm text-red-600 dark:text-red-400" role="alert">{{ error }}</p>

          <div class="mt-3 flex gap-2">
            <button
              v-if="canDraft"
              type="button"
              class="btn-ghost flex-1 justify-center"
              :disabled="submitting || uploading || videoBusy || !hasContent"
              data-testid="composer-save-draft"
              @click="submit('draft')"
            >
              {{ t("composer.saveDraft") }}
            </button>
            <button
              type="button"
              class="btn-primary flex-1 justify-center"
              :disabled="submitting || uploading || videoBusy || !hasContent"
              data-testid="composer-submit"
              @click="published ? saveEdit() : submit('publish')"
            >
              {{ primaryLabel }}
            </button>
          </div>
        </div>

        <!-- ================= audience ================= -->
        <div v-if="view === 'audience'" data-view class="min-h-0 flex-1 overflow-y-auto p-3" role="radiogroup" :aria-label="t('feed.audience')">
          <button
            v-for="a in AUDIENCES"
            :key="a.v"
            type="button"
            role="radio"
            :aria-checked="audience === a.v"
            class="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-start transition hover:bg-gray-100 dark:hover:bg-gray-800"
            :class="audience === a.v ? 'bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-200' : ''"
            @click="audience = a.v; view = 'main'"
          >
            <span class="flex h-10 w-10 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800">
              <component :is="a.icon" class="h-5 w-5" aria-hidden="true" />
            </span>
            <span class="flex-1 text-sm font-semibold">{{ t(a.label) }}</span>
            <Check v-if="audience === a.v" class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <!-- ================= tag people ================= -->
        <div v-if="view === 'tag'" data-view class="flex min-h-0 flex-1 flex-col p-3">
          <input
            v-model="friendQuery"
            type="search"
            class="input"
            dir="auto"
            :placeholder="t('composer.searchFriends')"
            :aria-label="t('composer.searchFriends')"
            data-testid="composer-friend-search"
          />
          <div v-if="taggedIds.length" class="mt-2 flex flex-wrap gap-1.5" :aria-label="t('composer.selected')" role="group">
            <button
              v-for="id in taggedIds"
              :key="id"
              type="button"
              class="chip chip-active"
              :aria-label="t('composer.removeTag', { name: directory.label(id) })"
              @click="toggleTag(id)"
            >
              <span dir="auto">{{ directory.label(id) }}</span> <X class="h-3 w-3" aria-hidden="true" />
            </button>
          </div>
          <p v-if="taggedIds.length >= MAX_TAGS" class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t("composer.tagLimit", { max: MAX_TAGS }) }}</p>
          <p class="mt-3 px-1 text-xs font-semibold text-gray-500 dark:text-gray-400">{{ t("composer.friendsList") }}</p>
          <ul class="mt-1 min-h-24 flex-1 space-y-0.5 overflow-y-auto" data-testid="composer-friends">
            <li v-for="f in shownFriends" :key="f.account_id">
              <label class="flex cursor-pointer items-center gap-3 rounded-xl px-2 py-1.5 transition hover:bg-gray-100 dark:hover:bg-gray-800">
                <UserAvatar :name="f.display_name || f.handle" :media-id="f.avatar_media_id" :size="36" />
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-sm font-semibold" dir="auto">{{ f.display_name || f.handle }}</span>
                  <span class="block truncate text-xs text-gray-500 dark:text-gray-400" dir="ltr">{{ "@" }}{{ f.handle }}</span>
                </span>
                <input
                  type="checkbox"
                  class="h-4 w-4 accent-brand-600"
                  :checked="taggedIds.includes(f.account_id)"
                  :disabled="!taggedIds.includes(f.account_id) && taggedIds.length >= MAX_TAGS"
                  @change="toggleTag(f.account_id)"
                />
              </label>
            </li>
            <li v-if="friendsLoading" class="px-2 py-2 text-xs text-gray-500 dark:text-gray-400">{{ t("composer.loadingFriends") }}</li>
            <li v-else-if="!shownFriends.length" class="px-2 py-2 text-sm text-gray-500 dark:text-gray-400">{{ t("composer.noFriends") }}</li>
          </ul>
          <button type="button" class="btn-primary mt-3 w-full justify-center" @click="view = 'main'">{{ t("composer.done") }}</button>
        </div>

        <!-- ================= feeling / activity ================= -->
        <div v-if="view === 'feeling'" data-view class="flex min-h-0 flex-1 flex-col p-3">
          <div class="flex gap-1.5" role="tablist" :aria-label="t('composer.feelingTabs')">
            <button type="button" role="tab" class="chip" :class="feelingTab === 'feelings' ? 'chip-active' : ''" :aria-selected="feelingTab === 'feelings'" @click="feelingTab = 'feelings'">
              {{ t("composer.feelingsTab") }}
            </button>
            <button type="button" role="tab" class="chip" :class="feelingTab === 'activities' ? 'chip-active' : ''" :aria-selected="feelingTab === 'activities'" @click="feelingTab = 'activities'">
              {{ t("composer.activitiesTab") }}
            </button>
          </div>
          <div class="mt-3 grid min-h-0 flex-1 grid-cols-2 gap-1 overflow-y-auto" role="tabpanel" data-testid="composer-feelings">
            <button
              v-for="key in feelingKeys"
              :key="key"
              type="button"
              class="flex items-center gap-2 rounded-xl px-3 py-2 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
              :class="feeling === key ? 'bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-200' : ''"
              :aria-pressed="feeling === key"
              @click="pickFeeling(key)"
            >
              <span class="text-lg" aria-hidden="true">{{ FEELING_EMOJI[key] }}</span>
              <span class="min-w-0 truncate">{{ t(`composer.feelings.${key}`) }}</span>
            </button>
          </div>
          <button v-if="feeling" type="button" class="btn-ghost mt-2 w-full justify-center" @click="feeling = ''; view = 'main'">
            {{ t("composer.clear") }}
          </button>
        </div>

        <!-- ================= schedule ================= -->
        <div v-if="view === 'schedule'" data-view class="min-h-0 flex-1 overflow-y-auto p-4">
          <label for="composer-schedule-at" class="block text-sm font-semibold">{{ t("composer.scheduleLabel") }}</label>
          <input
            id="composer-schedule-at"
            v-model="schedulePick"
            type="datetime-local"
            class="input mt-1"
            dir="ltr"
            :min="bounds.min"
            :max="bounds.max"
            aria-describedby="composer-schedule-hint"
            data-testid="composer-schedule-at"
          />
          <p id="composer-schedule-hint" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {{ t("composer.scheduleHint") }} {{ t("composer.timeZone", { zone }) }}
          </p>
          <p v-if="scheduleError" class="mt-2 text-sm text-red-600 dark:text-red-400" role="alert">{{ scheduleError }}</p>
          <div class="mt-4 flex gap-2">
            <button v-if="scheduleValue" type="button" class="btn-ghost flex-1 justify-center" @click="clearSchedule">{{ t("composer.clearSchedule") }}</button>
            <button type="button" class="btn-primary flex-1 justify-center" :disabled="!!scheduleError || !schedulePick" data-testid="composer-schedule-done" @click="confirmSchedule">
              {{ t("composer.done") }}
            </button>
          </div>
        </div>

        <!-- ================= drafts & scheduled ================= -->
        <div v-if="view === 'drafts'" data-view class="min-h-0 flex-1 overflow-y-auto p-3" data-testid="composer-drafts-list">
          <ul class="space-y-2">
            <li v-for="d in drafts" :key="d.id" class="rounded-xl border border-gray-200 p-3 dark:border-gray-700" :data-draft-id="d.id">
              <p class="text-xs font-semibold text-brand-700 dark:text-brand-300">
                {{ d.state === "scheduled" && d.publish_at ? t("composer.stateScheduled", { time: fmtTime(d.publish_at) }) : t("composer.stateDraft") }}
                <span class="font-normal text-gray-500 dark:text-gray-400">· {{ t("composer.edited", { time: relativeTime(d.updated_at ?? d.created_at) }) }}</span>
              </p>
              <p class="mt-1 line-clamp-3 whitespace-pre-line text-sm" dir="auto">{{ d.body || t("composer.emptyBody") }}</p>
              <div v-if="confirmingDelete === d.id" class="mt-2 flex flex-wrap items-center gap-2" role="group">
                <span class="text-sm">{{ t("composer.confirmDelete") }}</span>
                <button type="button" class="btn-ghost text-sm text-red-600 dark:text-red-400" @click="deleteFromList(d)">{{ t("composer.deleteDraft") }}</button>
                <button type="button" class="btn-ghost text-sm" @click="confirmingDelete = null">{{ t("feed.cancel") }}</button>
              </div>
              <div v-else class="mt-2 flex flex-wrap gap-1">
                <button type="button" class="btn-ghost text-sm" @click="load(d)">{{ t("composer.editDraft") }}</button>
                <button type="button" class="btn-ghost text-sm" @click="publishFromList(d)">{{ t("composer.publishNow") }}</button>
                <button type="button" class="btn-ghost ms-auto text-sm" :aria-label="`${t('composer.deleteDraft')}: ${d.body.slice(0, 40)}`" @click="confirmingDelete = d.id">
                  <Trash2 class="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
            </li>
          </ul>
          <p v-if="draftsLoading" class="px-2 py-3 text-xs text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
          <p v-else-if="!drafts.length" class="px-2 py-6 text-center text-sm text-gray-500 dark:text-gray-400">{{ t("composer.emptyDrafts") }}</p>
          <button v-if="draftsCursor && !draftsLoading" type="button" class="btn-ghost mt-2 w-full" @click="loadDrafts(false)">{{ t("composer.loadMore") }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
