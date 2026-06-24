<script setup lang="ts">
import { Camera, Plus, Trash2, X } from "lucide-vue-next";
import { reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { apiError } from "@/lib/api";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useMediaUrl } from "@/lib/useMediaUrl";
import { mediaService } from "@/services/media";
import { profileService } from "@/services/profile";
import { useAuthStore } from "@/stores/auth";
import type { Profile, ProfileEducation, ProfileLink, ProfileWork } from "@/types";

const props = defineProps<{ profile: Profile }>();
const emit = defineEmits<{ close: []; saved: [profile: Profile] }>();

const { t } = useI18n();
const auth = useAuthStore();
const open = ref(true);
useEscapeKey(open, () => emit("close"));

const VISIBILITY = [
  { v: "public", label: "profile.visibilityPublic" },
  { v: "friends_only", label: "profile.visibilityFriends" },
  { v: "private", label: "profile.visibilityPrivate" },
];

const form = reactive({
  display_name: props.profile.display_name ?? "",
  intro: props.profile.intro ?? "",
  bio: props.profile.bio ?? "",
  city: props.profile.city ?? "",
  country: props.profile.country ?? "",
  visibility: props.profile.visibility ?? "public",
});

// Avatar / cover: uploaded immediately, applied on Save.
const avatarId = ref<string | null>(props.profile.avatar_media_id);
const coverId = ref<string | null>(props.profile.cover_media_id);
const avatarUrl = useMediaUrl(() => avatarId.value);
const coverUrl = useMediaUrl(() => coverId.value);
const uploadingAvatar = ref(false);
const uploadingCover = ref(false);

// Structured sections — edited live against the API.
const links = ref<ProfileLink[]>([...(props.profile.links ?? [])]);
const education = ref<ProfileEducation[]>([...(props.profile.education ?? [])]);
const work = ref<ProfileWork[]>([...(props.profile.work ?? [])]);

const newLink = reactive({ label: "", url: "" });
const newWork = reactive({ company: "", title: "", is_current: false });
const newEdu = reactive({ school: "", field: "", start_year: "", end_year: "" });

const saving = ref(false);
const error = ref("");

async function pickAvatar(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;
  uploadingAvatar.value = true;
  try {
    avatarId.value = (await mediaService.upload(file, "image")).id;
  } catch (err) {
    error.value = apiError(err).message;
  } finally {
    uploadingAvatar.value = false;
  }
}
async function pickCover(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;
  uploadingCover.value = true;
  try {
    coverId.value = (await mediaService.upload(file, "image")).id;
  } catch (err) {
    error.value = apiError(err).message;
  } finally {
    uploadingCover.value = false;
  }
}

async function addLink() {
  if (!newLink.label.trim() || !newLink.url.trim()) return;
  try {
    const created = await profileService.addLink({ label: newLink.label.trim(), url: newLink.url.trim() });
    links.value.push(created);
    newLink.label = "";
    newLink.url = "";
  } catch (err) {
    error.value = apiError(err).message;
  }
}
async function dropLink(id: number) {
  try {
    await profileService.removeLink(id);
    links.value = links.value.filter((l) => l.id !== id);
  } catch {
    /* ignore */
  }
}

async function addWork() {
  if (!newWork.company.trim()) return;
  try {
    const created = await profileService.addWork({
      company: newWork.company.trim(),
      title: newWork.title.trim(),
      is_current: newWork.is_current,
    });
    work.value.push(created);
    newWork.company = "";
    newWork.title = "";
    newWork.is_current = false;
  } catch (err) {
    error.value = apiError(err).message;
  }
}
async function dropWork(id: number) {
  try {
    await profileService.removeWork(id);
    work.value = work.value.filter((w) => w.id !== id);
  } catch {
    /* ignore */
  }
}

async function addEducation() {
  if (!newEdu.school.trim()) return;
  try {
    const created = await profileService.addEducation({
      school: newEdu.school.trim(),
      field: newEdu.field.trim(),
      start_year: newEdu.start_year ? Number(newEdu.start_year) : null,
      end_year: newEdu.end_year ? Number(newEdu.end_year) : null,
    });
    education.value.push(created);
    newEdu.school = "";
    newEdu.field = "";
    newEdu.start_year = "";
    newEdu.end_year = "";
  } catch (err) {
    error.value = apiError(err).message;
  }
}
async function dropEducation(id: number) {
  try {
    await profileService.removeEducation(id);
    education.value = education.value.filter((e) => e.id !== id);
  } catch {
    /* ignore */
  }
}

async function save() {
  if (saving.value) return;
  saving.value = true;
  error.value = "";
  try {
    await profileService.update({
      display_name: form.display_name.trim(),
      intro: form.intro.trim(),
      bio: form.bio.trim(),
      city: form.city.trim(),
      country: form.country.trim(),
      visibility: form.visibility,
      avatar_media_id: avatarId.value,
      cover_media_id: coverId.value,
    });
    // Re-fetch the canonical profile (incl. completion %, structured lists).
    const fresh = await profileService.me();
    await auth.loadProfile();
    emit("saved", fresh);
  } catch (err) {
    error.value = apiError(err).message;
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4">
    <div class="fixed inset-0" @click="emit('close')" />
    <div
      class="card relative z-10 max-h-[94vh] w-full overflow-y-auto rounded-b-none rounded-t-2xl p-0 sm:max-w-lg sm:rounded-2xl"
    >
      <div class="sticky top-0 z-10 flex items-center justify-between border-b border-gray-100 bg-white/95 px-4 py-3 backdrop-blur dark:border-gray-800 dark:bg-gray-900/95">
        <h2 class="text-lg font-bold">{{ t("profile.editProfileTitle") }}</h2>
        <button class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" @click="emit('close')">
          <X class="h-5 w-5" />
        </button>
      </div>

      <div class="space-y-5 p-4">
        <!-- Cover + avatar -->
        <div>
          <p class="mb-1 text-sm font-medium">{{ t("profile.coverPhoto") }}</p>
          <div class="relative h-28 overflow-hidden rounded-xl bg-gradient-to-r from-brand-100 to-brand-50 dark:from-brand-900/40 dark:to-gray-800">
            <img v-if="coverUrl" :src="coverUrl" class="h-full w-full object-cover" alt="" />
            <label class="absolute end-2 top-2 flex cursor-pointer items-center gap-1 rounded-full bg-black/55 px-2.5 py-1 text-xs font-medium text-white">
              <Camera class="h-3.5 w-3.5" /> {{ uploadingCover ? t("profile.uploading") : t("profile.change") }}
              <input type="file" accept="image/*" class="hidden" @change="pickCover" />
            </label>
          </div>
          <div class="-mt-8 ms-4 inline-block">
            <div class="relative">
              <span class="block rounded-full border-4 border-white dark:border-gray-900">
                <UserAvatar :name="form.display_name || '?'" :media-id="avatarId" :size="72" :key="avatarUrl || ''" />
              </span>
              <label class="absolute -end-1 -bottom-1 flex h-7 w-7 cursor-pointer items-center justify-center rounded-full bg-brand-600 text-white shadow">
                <Camera class="h-3.5 w-3.5" />
                <input type="file" accept="image/*" class="hidden" @change="pickAvatar" />
              </label>
            </div>
          </div>
          <p v-if="uploadingAvatar" class="mt-1 text-xs text-gray-400">{{ t("profile.uploading") }}</p>
        </div>

        <!-- Core fields -->
        <div class="space-y-3">
          <div>
            <label class="mb-1 block text-sm font-medium">{{ t("auth.displayName") }}</label>
            <input v-model="form.display_name" class="input" maxlength="120" />
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium">{{ t("profile.intro") }}</label>
            <input v-model="form.intro" class="input" :placeholder="t('profile.intro')" maxlength="160" />
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium">{{ t("profile.bioLabel") }}</label>
            <textarea v-model="form.bio" class="input min-h-20" rows="3" />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="mb-1 block text-sm font-medium">{{ t("profile.location") }}</label>
              <input v-model="form.city" class="input" :placeholder="t('profile.location')" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium">&nbsp;</label>
              <input v-model="form.country" class="input" placeholder="—" />
            </div>
          </div>
          <div>
            <label class="mb-1 block text-sm font-medium">{{ t("profile.visibility") }}</label>
            <select v-model="form.visibility" class="input">
              <option v-for="v in VISIBILITY" :key="v.v" :value="v.v">{{ t(v.label) }}</option>
            </select>
          </div>
        </div>

        <!-- Links -->
        <section>
          <h3 class="mb-2 text-sm font-bold">{{ t("profile.links") }}</h3>
          <ul class="mb-2 space-y-1">
            <li v-for="l in links" :key="l.id" class="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-1.5 text-sm dark:bg-gray-800/60">
              <span class="min-w-0 flex-1 truncate">{{ l.label }} · <span class="text-gray-400">{{ l.url }}</span></span>
              <button class="text-gray-400 hover:text-red-500" @click="dropLink(l.id)"><Trash2 class="h-4 w-4" /></button>
            </li>
          </ul>
          <div class="flex gap-2">
            <input v-model="newLink.label" class="input" :placeholder="t('profile.label')" />
            <input v-model="newLink.url" class="input" :placeholder="t('profile.url')" />
            <button class="btn-ghost shrink-0 px-2" :aria-label="t('profile.addLink')" @click="addLink"><Plus class="h-4 w-4" /></button>
          </div>
        </section>

        <!-- Work -->
        <section>
          <h3 class="mb-2 text-sm font-bold">{{ t("profile.work") }}</h3>
          <ul class="mb-2 space-y-1">
            <li v-for="w in work" :key="w.id" class="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-1.5 text-sm dark:bg-gray-800/60">
              <span class="min-w-0 flex-1 truncate">
                {{ w.title || "—" }}<span v-if="w.company"> · {{ w.company }}</span>
                <span v-if="w.is_current" class="text-xs text-brand-600"> ({{ t("profile.present") }})</span>
              </span>
              <button class="text-gray-400 hover:text-red-500" @click="dropWork(w.id)"><Trash2 class="h-4 w-4" /></button>
            </li>
          </ul>
          <div class="space-y-2">
            <div class="flex gap-2">
              <input v-model="newWork.title" class="input" :placeholder="t('profile.jobTitle')" />
              <input v-model="newWork.company" class="input" :placeholder="t('profile.company')" />
              <button class="btn-ghost shrink-0 px-2" :aria-label="t('profile.addWork')" @click="addWork"><Plus class="h-4 w-4" /></button>
            </div>
            <label class="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
              <input v-model="newWork.is_current" type="checkbox" class="rounded" /> {{ t("profile.current") }}
            </label>
          </div>
        </section>

        <!-- Education -->
        <section>
          <h3 class="mb-2 text-sm font-bold">{{ t("profile.education") }}</h3>
          <ul class="mb-2 space-y-1">
            <li v-for="e in education" :key="e.id" class="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-1.5 text-sm dark:bg-gray-800/60">
              <span class="min-w-0 flex-1 truncate">
                {{ e.school }}<span v-if="e.field"> · {{ e.field }}</span>
                <span v-if="e.start_year || e.end_year" class="text-xs text-gray-400"> ({{ e.start_year || "?" }}–{{ e.end_year || t("profile.present") }})</span>
              </span>
              <button class="text-gray-400 hover:text-red-500" @click="dropEducation(e.id)"><Trash2 class="h-4 w-4" /></button>
            </li>
          </ul>
          <div class="space-y-2">
            <div class="flex gap-2">
              <input v-model="newEdu.school" class="input" :placeholder="t('profile.school')" />
              <input v-model="newEdu.field" class="input" :placeholder="t('profile.fieldOfStudy')" />
            </div>
            <div class="flex gap-2">
              <input v-model="newEdu.start_year" type="number" class="input" :placeholder="t('profile.startYear')" />
              <input v-model="newEdu.end_year" type="number" class="input" :placeholder="t('profile.endYear')" />
              <button class="btn-ghost shrink-0 px-2" :aria-label="t('profile.addEducation')" @click="addEducation"><Plus class="h-4 w-4" /></button>
            </div>
          </div>
        </section>

        <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
      </div>

      <div class="sticky bottom-0 flex justify-end gap-2 border-t border-gray-100 bg-white/95 px-4 py-3 backdrop-blur dark:border-gray-800 dark:bg-gray-900/95">
        <button class="btn-ghost" @click="emit('close')">{{ t("feed.cancel") }}</button>
        <button class="btn-primary" :disabled="saving" @click="save">
          {{ saving ? t("profile.saving") : t("profile.save") }}
        </button>
      </div>
    </div>
  </div>
</template>
