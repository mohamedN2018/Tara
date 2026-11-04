<script setup lang="ts">
import { ArrowLeft, ArrowRight, Globe, ImagePlus, Lock, Star, Type, Users } from "lucide-vue-next";
import { computed, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";

import { IMAGE_ACCEPT } from "@/lib/heic";
import {
  backgroundStyle,
  STORY_AUDIENCES,
  STORY_BACKGROUNDS,
  STORY_ERRORS,
  STORY_MAX_TEXT,
  storiesService,
  type Story,
  type StoryAudience,
  type StoryBackground,
  type StoryKind,
} from "@/services/stories";
import { useToastStore } from "@/stores/toasts";

import CloseFriendsDialog from "./CloseFriendsDialog.vue";
import StoryDialog from "./StoryDialog.vue";

// Create a story: a photo (uploaded through the media flow, then bound to the
// story and restricted to its audience) or text on a brand gradient. The
// audience is the author's choice; the last one is remembered on this device.
const props = withDefaults(defineProps<{ initialKind?: StoryKind | null }>(), { initialKind: null });
const emit = defineEmits<{ close: []; created: [story: Story] }>();

const { t, locale } = useI18n();
const toasts = useToastStore();

const AUDIENCE_KEY = "tara.storyAudience";
function savedAudience(): StoryAudience {
  try {
    const v = localStorage.getItem(AUDIENCE_KEY);
    return (STORY_AUDIENCES as string[]).includes(v ?? "") ? (v as StoryAudience) : "friends";
  } catch {
    return "friends";
  }
}

const kind = ref<StoryKind | null>(props.initialKind);
const audience = ref<StoryAudience>(savedAudience());
const text = ref("");
const background = ref<StoryBackground>("violet");
const file = ref<File | null>(null);
const preview = ref<string | null>(null);
const sending = ref(false);
const phase = ref<"idle" | "uploading" | "sharing">("idle");
const showCloseFriends = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);

const AUDIENCE_ICONS = { public: Globe, friends: Users, close_friends: Star } as const;
const BackIcon = computed(() => (locale.value === "ar" ? ArrowRight : ArrowLeft));

const canShare = computed(() =>
  kind.value === "text" ? text.value.trim().length > 0 && text.value.length <= STORY_MAX_TEXT : !!file.value,
);

function revoke() {
  if (preview.value) URL.revokeObjectURL(preview.value);
  preview.value = null;
}
onBeforeUnmount(revoke);

function pickPhoto() {
  fileInput.value?.click();
}
function onFile(e: Event) {
  const input = e.target as HTMLInputElement;
  const picked = input.files?.[0];
  input.value = "";
  if (!picked) return;
  revoke();
  file.value = picked;
  preview.value = URL.createObjectURL(picked);
  kind.value = "photo";
}
function choose(next: StoryKind) {
  kind.value = next;
  if (next === "photo" && !file.value) pickPhoto();
}
function back() {
  kind.value = null;
  file.value = null;
  revoke();
}

async function share() {
  if (!kind.value || !canShare.value || sending.value) return;
  sending.value = true;
  try {
    let mediaId: string | null = null;
    if (kind.value === "photo" && file.value) {
      phase.value = "uploading";
      mediaId = await storiesService.uploadPhoto(file.value);
    }
    phase.value = "sharing";
    const story = await storiesService.create({
      kind: kind.value,
      audience: audience.value,
      text: text.value.trim(),
      background: background.value,
      media_id: mediaId,
    });
    try {
      localStorage.setItem(AUDIENCE_KEY, audience.value);
    } catch {
      // Remembered for this visit only.
    }
    toasts.success(t("stories.create.shared"));
    emit("created", story);
    emit("close");
  } catch (e) {
    toasts.error(e, STORY_ERRORS);
  } finally {
    sending.value = false;
    phase.value = "idle";
  }
}
</script>

<template>
  <StoryDialog :title="t('stories.create.title')" :close-label="t('stories.viewer.close')" wide @close="!sending && !showCloseFriends && emit('close')">
    <input ref="fileInput" type="file" class="hidden" :accept="IMAGE_ACCEPT" data-testid="story-file" @change="onFile" />

    <!-- Step 1: what kind of story -->
    <div v-if="!kind" class="grid grid-cols-2 gap-3 py-2 sm:gap-4" data-testid="story-kind-picker">
      <button
        type="button"
        class="flex aspect-[3/4] flex-col items-center justify-center gap-3 rounded-2xl bg-gradient-to-br from-brand-600 to-accent-500 p-4 text-white shadow-glow transition hover:brightness-110 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-300"
        data-testid="story-kind-photo"
        @click="choose('photo')"
      >
        <span class="flex h-12 w-12 items-center justify-center rounded-full bg-white/20"><ImagePlus class="h-6 w-6" aria-hidden="true" /></span>
        <span class="text-base font-bold">{{ t("stories.create.photo") }}</span>
        <span class="text-xs text-white/80">{{ t("stories.create.photoHint") }}</span>
      </button>
      <button
        type="button"
        class="flex aspect-[3/4] flex-col items-center justify-center gap-3 rounded-2xl bg-gradient-to-br from-gray-950 to-brand-600 p-4 text-white shadow-glow transition hover:brightness-110 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-300"
        data-testid="story-kind-text"
        @click="choose('text')"
      >
        <span class="flex h-12 w-12 items-center justify-center rounded-full bg-white/20"><Type class="h-6 w-6" aria-hidden="true" /></span>
        <span class="text-base font-bold">{{ t("stories.create.text") }}</span>
        <span class="text-xs text-white/80">{{ t("stories.create.textHint") }}</span>
      </button>
    </div>

    <!-- Step 2: settings beside a live preview -->
    <div v-else class="grid min-h-0 gap-4 overflow-y-auto sm:grid-cols-[minmax(0,1fr)_260px]">
      <div class="space-y-4">
        <template v-if="kind === 'text'">
          <label class="block">
            <span class="mb-1 block text-sm font-semibold">{{ t("stories.create.textLabel") }}</span>
            <textarea
              v-model="text"
              rows="4"
              dir="auto"
              class="input resize-none"
              :maxlength="STORY_MAX_TEXT"
              :placeholder="t('stories.create.textPlaceholder')"
              data-testid="story-text"
            />
            <span class="mt-1 block text-end text-xs text-gray-500 dark:text-gray-400">
              {{ t("stories.create.chars", { n: text.length, max: STORY_MAX_TEXT }) }}
            </span>
          </label>
          <fieldset>
            <legend class="mb-2 text-sm font-semibold">{{ t("stories.create.background") }}</legend>
            <div class="flex flex-wrap gap-2">
              <label v-for="bg in STORY_BACKGROUNDS" :key="bg" class="cursor-pointer">
                <input v-model="background" type="radio" name="story-bg" :value="bg" class="peer sr-only" />
                <span
                  class="block h-9 w-9 rounded-full ring-offset-2 transition peer-checked:ring-2 peer-checked:ring-brand-500 peer-focus-visible:ring-2 peer-focus-visible:ring-brand-400 dark:ring-offset-gray-900"
                  :style="{ backgroundImage: backgroundStyle(bg) }"
                  :title="t(`stories.create.backgrounds.${bg}`)"
                />
                <span class="sr-only">{{ t(`stories.create.backgrounds.${bg}`) }}</span>
              </label>
            </div>
          </fieldset>
        </template>
        <template v-else>
          <button type="button" class="btn-outline w-full" @click="pickPhoto">
            <ImagePlus class="h-4 w-4" aria-hidden="true" />
            {{ file ? t("stories.create.changePhoto") : t("stories.create.choosePhoto") }}
          </button>
          <label class="block">
            <span class="mb-1 block text-sm font-semibold">{{ t("stories.create.caption") }}</span>
            <input v-model="text" type="text" dir="auto" class="input" :maxlength="STORY_MAX_TEXT" data-testid="story-caption" />
          </label>
        </template>

        <fieldset>
          <legend class="mb-2 text-sm font-semibold">{{ t("stories.create.audience") }}</legend>
          <div class="space-y-1.5">
            <label
              v-for="a in STORY_AUDIENCES"
              :key="a"
              class="flex cursor-pointer items-center gap-3 rounded-xl border border-gray-200 px-3 py-2 transition has-[:checked]:border-brand-500 has-[:checked]:bg-brand-50 dark:border-gray-800 dark:has-[:checked]:bg-brand-950/50"
            >
              <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200">
                <component :is="AUDIENCE_ICONS[a]" class="h-4 w-4" aria-hidden="true" />
              </span>
              <span class="min-w-0 flex-1">
                <span class="block text-sm font-semibold">{{ t(`stories.create.audiences.${a}`) }}</span>
                <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t(`stories.create.audienceHints.${a}`) }}</span>
              </span>
              <input v-model="audience" type="radio" name="story-audience" :value="a" class="h-4 w-4 accent-brand-600" :data-testid="`story-audience-${a}`" />
            </label>
          </div>
          <button
            type="button"
            class="mt-2 text-sm font-semibold text-brand-700 hover:underline dark:text-brand-300"
            data-testid="story-manage-close-friends"
            @click="showCloseFriends = true"
          >
            {{ t("stories.create.manageCloseFriends") }}
          </button>
        </fieldset>
      </div>

      <div class="order-first sm:order-none">
        <p class="mb-2 text-sm font-semibold">{{ t("stories.create.preview") }}</p>
        <div
          class="relative mx-auto aspect-[9/16] w-40 overflow-hidden rounded-xl bg-gray-900 sm:w-full"
          :style="kind === 'text' ? { backgroundImage: backgroundStyle(background) } : undefined"
          data-testid="story-preview"
        >
          <img v-if="kind === 'photo' && preview" :src="preview" alt="" class="absolute inset-0 h-full w-full object-contain" />
          <button
            v-else-if="kind === 'photo'"
            type="button"
            class="absolute inset-0 flex flex-col items-center justify-center gap-2 text-sm text-white/80"
            @click="pickPhoto"
          >
            <ImagePlus class="h-8 w-8" aria-hidden="true" />{{ t("stories.create.choosePhoto") }}
          </button>
          <p
            v-if="kind === 'text'"
            dir="auto"
            class="absolute inset-0 flex items-center justify-center whitespace-pre-wrap break-words p-4 text-center text-lg font-bold leading-snug text-white"
          >
            {{ text || t("stories.create.textPlaceholder") }}
          </p>
          <p
            v-else-if="text"
            dir="auto"
            class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-3 pt-8 text-center text-sm font-semibold text-white"
          >
            {{ text }}
          </p>
          <span class="absolute end-2 top-2 inline-flex items-center gap-1 rounded-full bg-black/40 px-2 py-0.5 text-[11px] font-semibold text-white">
            <Lock v-if="audience !== 'public'" class="h-3 w-3" aria-hidden="true" />
            {{ t(`stories.create.audiences.${audience}`) }}
          </span>
        </div>
      </div>

      <div class="flex items-center justify-between gap-2 border-t border-gray-100 pt-3 sm:col-span-2 dark:border-gray-800">
        <button type="button" class="btn-ghost" :disabled="sending" @click="back">
          <component :is="BackIcon" class="h-4 w-4" aria-hidden="true" />{{ t("stories.create.back") }}
        </button>
        <button type="button" class="btn-gradient" :disabled="!canShare || sending" data-testid="story-share" @click="share">
          {{
            phase === "uploading" ? t("stories.create.uploading") : phase === "sharing" ? t("stories.create.sharing") : t("stories.create.share")
          }}
        </button>
      </div>
    </div>

    <CloseFriendsDialog v-if="showCloseFriends" inline @close="showCloseFriends = false" />
  </StoryDialog>
</template>
