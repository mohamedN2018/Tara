<script setup lang="ts">
import { Briefcase, CalendarDays, GraduationCap, Home, LinkIcon, MapPin, Plus, Quote, Trash2, UserRound } from "lucide-vue-next";
import { computed, onMounted, reactive, ref, toRefs } from "vue";
import { useI18n } from "vue-i18n";

import AudienceSelect from "@/components/profile/AudienceSelect.vue";
import { degreeField, educationHeadline, educationRange, linkHost, workHeadline, workRange } from "@/lib/profileFormat";
import type { ProfileState } from "@/lib/useProfile";
import { type FieldPrivacy, profileService } from "@/services/profile";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";
import type { Profile } from "@/types";

// About tab (reference layout): a section list at the start, the section's
// content beside it. The owner edits each section in place (work, education,
// places, links, intro/bio) and sets each field's audience; visitors only see
// what the server already filtered for them.
const props = defineProps<{ state: ProfileState }>();

type Section = "overview" | "work" | "places" | "contact" | "details";
const SECTIONS: Section[] = ["overview", "work", "places", "contact", "details"];

const { profile, isSelf, joinedText } = toRefs(props.state);
const { t, locale } = useI18n();
const auth = useAuthStore();
const toasts = useToastStore();
const section = ref<Section>("overview");

// ---- field audiences (owner) ----
const privacy = ref<Record<string, string> | null>(null);
const savingPrivacy = ref("");
onMounted(async () => {
  if (!isSelf.value) return;
  try {
    const items = await profileService.fieldPrivacy();
    privacy.value = Object.fromEntries(items.map((i) => [i.field_key, i.visibility]));
  } catch {
    privacy.value = null; // Selectors stay hidden rather than showing a guess.
  }
});
async function setAudience(field: string, visibility: string) {
  if (!privacy.value) return;
  const before = privacy.value[field];
  privacy.value = { ...privacy.value, [field]: visibility };
  savingPrivacy.value = field;
  try {
    await profileService.setFieldPrivacy([{ field_key: field, visibility } as FieldPrivacy]);
  } catch (e) {
    privacy.value = { ...privacy.value, [field]: before };
    toasts.error(e);
  } finally {
    savingPrivacy.value = "";
  }
}

function patchProfile(changes: Partial<Profile>) {
  props.state.patchProfile(changes);
  void auth.loadProfile();
}

// ---- work ----
const addingWork = ref(false);
const work = reactive({ company: "", title: "", start_date: "", end_date: "", is_current: false });
async function saveWork() {
  if (!work.company.trim()) return;
  try {
    const created = await profileService.addWork({
      company: work.company.trim(),
      title: work.title.trim(),
      start_date: work.start_date || null,
      end_date: work.is_current ? null : work.end_date || null,
      is_current: work.is_current,
    });
    patchProfile({ work: [...(profile.value?.work ?? []), created] });
    Object.assign(work, { company: "", title: "", start_date: "", end_date: "", is_current: false });
    addingWork.value = false;
  } catch (e) {
    toasts.error(e);
  }
}
async function dropWork(id: number) {
  try {
    await profileService.removeWork(id);
    patchProfile({ work: (profile.value?.work ?? []).filter((w) => w.id !== id) });
  } catch (e) {
    toasts.error(e);
  }
}

// ---- education ----
const addingEdu = ref(false);
const edu = reactive({ school: "", degree: "", field: "", start_year: "", end_year: "" });
async function saveEdu() {
  if (!edu.school.trim()) return;
  try {
    const created = await profileService.addEducation({
      school: edu.school.trim(),
      degree: edu.degree.trim(),
      field: edu.field.trim(),
      start_year: edu.start_year ? Number(edu.start_year) : null,
      end_year: edu.end_year ? Number(edu.end_year) : null,
    });
    patchProfile({ education: [...(profile.value?.education ?? []), created] });
    Object.assign(edu, { school: "", degree: "", field: "", start_year: "", end_year: "" });
    addingEdu.value = false;
  } catch (e) {
    toasts.error(e);
  }
}
async function dropEdu(id: number) {
  try {
    await profileService.removeEducation(id);
    patchProfile({ education: (profile.value?.education ?? []).filter((e) => e.id !== id) });
  } catch (e) {
    toasts.error(e);
  }
}

// ---- links ----
const addingLink = ref(false);
const link = reactive({ label: "", url: "" });
async function saveLink() {
  if (!link.url.trim()) return;
  try {
    const created = await profileService.addLink({ label: link.label.trim() || linkHost(link.url.trim()), url: link.url.trim() });
    patchProfile({ links: [...(profile.value?.links ?? []), created] });
    Object.assign(link, { label: "", url: "" });
    addingLink.value = false;
  } catch (e) {
    toasts.error(e);
  }
}
async function dropLink(id: number) {
  try {
    await profileService.removeLink(id);
    patchProfile({ links: (profile.value?.links ?? []).filter((l) => l.id !== id) });
  } catch (e) {
    toasts.error(e);
  }
}

// ---- scalar fields: places (city, country) and details (intro, bio) ----
const editing = ref<"" | "places" | "details">("");
const scalars = reactive({ city: "", country: "", intro: "", bio: "" });
const savingScalars = ref(false);
function startEdit(which: "places" | "details") {
  Object.assign(scalars, {
    city: profile.value?.city ?? "",
    country: profile.value?.country ?? "",
    intro: profile.value?.intro ?? "",
    bio: profile.value?.bio ?? "",
  });
  editing.value = which;
}
async function saveScalars() {
  if (savingScalars.value) return;
  savingScalars.value = true;
  const changes =
    editing.value === "places"
      ? { city: scalars.city.trim(), country: scalars.country.trim() }
      : { intro: scalars.intro.trim(), bio: scalars.bio.trim() };
  try {
    const fresh = await profileService.update(changes);
    patchProfile({ ...changes, completion_pct: fresh.completion_pct });
    editing.value = "";
    toasts.success(t("people.about.saved"));
  } catch (e) {
    toasts.error(e);
  } finally {
    savingScalars.value = false;
  }
}

const place = computed(() => [profile.value?.city, profile.value?.country].filter(Boolean).join(", "));
const currentWork = computed(() => profile.value?.work?.find((w) => w.is_current) ?? profile.value?.work?.[0]);
const lastEdu = computed(() => profile.value?.education?.[0]);

const row = "flex items-start gap-3 py-2";
const iconCls = "mt-0.5 h-6 w-6 shrink-0 text-gray-500 dark:text-gray-400";
const addBtn =
  "flex w-full items-center gap-3 rounded-lg px-2 py-2 text-start text-[15px] font-medium text-brand-600 transition hover:bg-brand-50 dark:text-brand-300 dark:hover:bg-brand-950/40";
const delBtn = "rounded-full p-2 text-gray-500 transition hover:bg-gray-100 hover:text-red-600 dark:text-gray-400 dark:hover:bg-gray-800";
</script>

<template>
  <section class="card overflow-hidden lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]" data-testid="profile-about-tab">
    <!-- Section list -->
    <nav class="border-b border-gray-200 p-3 dark:border-gray-800 lg:border-b-0 lg:border-e" :aria-label="t('people.about.nav')">
      <h2 class="mb-2 px-2 text-xl font-bold">{{ t("people.about.title") }}</h2>
      <ul class="flex gap-1 overflow-x-auto lg:block lg:space-y-0.5">
        <li v-for="s in SECTIONS" :key="s" class="shrink-0">
          <button
            type="button"
            class="w-full whitespace-nowrap rounded-lg px-3 py-2 text-start text-[15px] font-semibold transition lg:whitespace-normal"
            :class="section === s ? 'bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-300' : 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'"
            :aria-current="section === s ? 'true' : undefined"
            :data-testid="`about-section-${s}`"
            @click="section = s"
          >
            {{ t(`people.about.sections.${s}`) }}
          </button>
        </li>
      </ul>
    </nav>

    <div class="min-w-0 p-4 sm:p-6">
      <!-- Overview -->
      <div v-if="section === 'overview'" class="divide-y divide-gray-100 dark:divide-gray-800">
        <div :class="row">
          <Briefcase :class="iconCls" />
          <span v-if="currentWork" class="min-w-0 flex-1 text-[15px]" dir="auto">{{ workHeadline(currentWork, t) }}</span>
          <button v-else-if="isSelf" type="button" class="-my-2 flex-1 text-start text-[15px] font-medium text-brand-600 hover:underline dark:text-brand-300" @click="section = 'work'; addingWork = true">{{ t("people.about.addWork") }}</button>
          <span v-else class="flex-1 text-[15px] text-gray-500 dark:text-gray-400">{{ t("people.about.nothing") }}</span>
        </div>
        <div :class="row">
          <GraduationCap :class="iconCls" />
          <span v-if="lastEdu" class="min-w-0 flex-1 text-[15px]" dir="auto">{{ educationHeadline(lastEdu, t) }}</span>
          <button v-else-if="isSelf" type="button" class="-my-2 flex-1 text-start text-[15px] font-medium text-brand-600 hover:underline dark:text-brand-300" @click="section = 'work'; addingEdu = true">{{ t("people.about.addEducation") }}</button>
          <span v-else class="flex-1 text-[15px] text-gray-500 dark:text-gray-400">{{ t("people.about.nothing") }}</span>
        </div>
        <div :class="row">
          <Home :class="iconCls" />
          <span v-if="place" class="min-w-0 flex-1 text-[15px]" dir="auto">{{ t("people.intro.livesIn", { place }) }}</span>
          <button v-else-if="isSelf" type="button" class="-my-2 flex-1 text-start text-[15px] font-medium text-brand-600 hover:underline dark:text-brand-300" @click="section = 'places'; startEdit('places')">{{ t("people.about.addPlace") }}</button>
          <span v-else class="flex-1 text-[15px] text-gray-500 dark:text-gray-400">{{ t("people.about.nothing") }}</span>
        </div>
        <div v-if="profile?.links?.length" :class="row">
          <LinkIcon :class="iconCls" />
          <span class="flex min-w-0 flex-1 flex-wrap gap-x-2 text-[15px]">
            <a v-for="l in profile.links" :key="l.id" :href="l.url" target="_blank" rel="noopener noreferrer" class="font-medium text-brand-600 hover:underline dark:text-brand-300" dir="auto">{{ l.label || linkHost(l.url) }}</a>
          </span>
        </div>
        <div v-if="profile?.created_at" :class="row">
          <CalendarDays :class="iconCls" />
          <span class="flex-1 text-[15px]">{{ joinedText(profile.created_at) }}</span>
        </div>
      </div>

      <!-- Work and education -->
      <div v-else-if="section === 'work'" class="space-y-6">
        <div>
          <div class="mb-2 flex items-center justify-between gap-2">
            <h3 class="text-[17px] font-bold">{{ t("people.about.work") }}</h3>
            <AudienceSelect v-if="isSelf && privacy" field="work" :model-value="privacy.work ?? 'public'" :disabled="savingPrivacy === 'work'" @update:model-value="setAudience('work', $event)" />
          </div>
          <button v-if="isSelf && !addingWork" type="button" :class="addBtn" data-testid="about-add-work" @click="addingWork = true">
            <Plus class="h-6 w-6 rounded-full border-2 border-current p-0.5" /> {{ t("people.about.addWork") }}
          </button>
          <form v-if="isSelf && addingWork" class="mb-3 space-y-2 rounded-xl border border-gray-200 p-3 dark:border-gray-800" data-testid="about-work-form" @submit.prevent="saveWork">
            <input v-model="work.company" class="input" dir="auto" :placeholder="t('people.about.company')" :aria-label="t('people.about.company')" maxlength="120" required />
            <input v-model="work.title" class="input" dir="auto" :placeholder="t('people.about.jobTitle')" :aria-label="t('people.about.jobTitle')" maxlength="120" />
            <div class="grid grid-cols-2 gap-2">
              <label class="text-xs font-medium text-gray-600 dark:text-gray-300">{{ t("people.about.startDate") }}
                <input v-model="work.start_date" type="date" class="input mt-1" />
              </label>
              <label class="text-xs font-medium text-gray-600 dark:text-gray-300">{{ t("people.about.endDate") }}
                <input v-model="work.end_date" type="date" class="input mt-1" :disabled="work.is_current" />
              </label>
            </div>
            <label class="flex items-center gap-2 text-sm"><input v-model="work.is_current" type="checkbox" class="rounded accent-brand-600" /> {{ t("people.about.current") }}</label>
            <div class="flex justify-end gap-2">
              <button type="button" class="btn-ghost" @click="addingWork = false">{{ t("people.about.cancel") }}</button>
              <button type="submit" class="btn-primary" :disabled="!work.company.trim()">{{ t("people.about.save") }}</button>
            </div>
          </form>
          <ul>
            <li v-for="w in profile?.work ?? []" :key="w.id" :class="row" data-testid="about-work-item">
              <Briefcase :class="iconCls" />
              <span class="min-w-0 flex-1">
                <span class="block text-[15px]" dir="auto">{{ workHeadline(w, t) }}</span>
                <span v-if="workRange(w, t, locale)" class="block text-sm text-gray-500 dark:text-gray-400">{{ workRange(w, t, locale) }}</span>
              </span>
              <button v-if="isSelf" type="button" :class="delBtn" :aria-label="t('people.about.deleteItem', { name: w.company })" @click="dropWork(w.id)"><Trash2 class="h-4 w-4" /></button>
            </li>
          </ul>
          <p v-if="!isSelf && !profile?.work?.length" class="text-[15px] text-gray-500 dark:text-gray-400">{{ t("people.about.nothing") }}</p>
        </div>

        <div>
          <div class="mb-2 flex items-center justify-between gap-2">
            <h3 class="text-[17px] font-bold">{{ t("people.about.education") }}</h3>
            <AudienceSelect v-if="isSelf && privacy" field="education" :model-value="privacy.education ?? 'public'" :disabled="savingPrivacy === 'education'" @update:model-value="setAudience('education', $event)" />
          </div>
          <button v-if="isSelf && !addingEdu" type="button" :class="addBtn" data-testid="about-add-education" @click="addingEdu = true">
            <Plus class="h-6 w-6 rounded-full border-2 border-current p-0.5" /> {{ t("people.about.addEducation") }}
          </button>
          <form v-if="isSelf && addingEdu" class="mb-3 space-y-2 rounded-xl border border-gray-200 p-3 dark:border-gray-800" data-testid="about-education-form" @submit.prevent="saveEdu">
            <input v-model="edu.school" class="input" dir="auto" :placeholder="t('people.about.school')" :aria-label="t('people.about.school')" maxlength="120" required />
            <div class="grid grid-cols-2 gap-2">
              <input v-model="edu.degree" class="input" dir="auto" :placeholder="t('people.about.degree')" :aria-label="t('people.about.degree')" maxlength="120" />
              <input v-model="edu.field" class="input" dir="auto" :placeholder="t('people.about.field')" :aria-label="t('people.about.field')" maxlength="120" />
              <input v-model="edu.start_year" type="number" min="1900" max="2100" class="input" :placeholder="t('people.about.startYear')" :aria-label="t('people.about.startYear')" />
              <input v-model="edu.end_year" type="number" min="1900" max="2100" class="input" :placeholder="t('people.about.endYear')" :aria-label="t('people.about.endYear')" />
            </div>
            <div class="flex justify-end gap-2">
              <button type="button" class="btn-ghost" @click="addingEdu = false">{{ t("people.about.cancel") }}</button>
              <button type="submit" class="btn-primary" :disabled="!edu.school.trim()">{{ t("people.about.save") }}</button>
            </div>
          </form>
          <ul>
            <li v-for="e in profile?.education ?? []" :key="e.id" :class="row" data-testid="about-education-item">
              <GraduationCap :class="iconCls" />
              <span class="min-w-0 flex-1">
                <span class="block text-[15px]" dir="auto">{{ educationHeadline(e, t) }}</span>
                <span v-if="degreeField(e, t) || educationRange(e, t)" class="block text-sm text-gray-500 dark:text-gray-400" dir="auto">
                  {{ [degreeField(e, t), educationRange(e, t)].filter(Boolean).join(" · ") }}
                </span>
              </span>
              <button v-if="isSelf" type="button" :class="delBtn" :aria-label="t('people.about.deleteItem', { name: e.school })" @click="dropEdu(e.id)"><Trash2 class="h-4 w-4" /></button>
            </li>
          </ul>
          <p v-if="!isSelf && !profile?.education?.length" class="text-[15px] text-gray-500 dark:text-gray-400">{{ t("people.about.nothing") }}</p>
        </div>
      </div>

      <!-- Places -->
      <div v-else-if="section === 'places'">
        <h3 class="mb-2 text-[17px] font-bold">{{ t("people.about.places") }}</h3>
        <form v-if="isSelf && editing === 'places'" class="space-y-2 rounded-xl border border-gray-200 p-3 dark:border-gray-800" data-testid="about-places-form" @submit.prevent="saveScalars">
          <input v-model="scalars.city" class="input" dir="auto" :placeholder="t('people.about.city')" :aria-label="t('people.about.city')" maxlength="80" />
          <input v-model="scalars.country" class="input" dir="auto" :placeholder="t('people.about.country')" :aria-label="t('people.about.country')" maxlength="80" />
          <div class="flex justify-end gap-2">
            <button type="button" class="btn-ghost" @click="editing = ''">{{ t("people.about.cancel") }}</button>
            <button type="submit" class="btn-primary" :disabled="savingScalars">{{ t("people.about.save") }}</button>
          </div>
        </form>
        <template v-else>
          <div v-if="profile?.city" :class="row">
            <Home :class="iconCls" />
            <span class="min-w-0 flex-1"><span class="block text-[15px]" dir="auto">{{ profile.city }}</span><span class="block text-sm text-gray-500 dark:text-gray-400">{{ t("people.about.city") }}</span></span>
            <AudienceSelect v-if="isSelf && privacy" field="city" :model-value="privacy.city ?? 'public'" :disabled="savingPrivacy === 'city'" @update:model-value="setAudience('city', $event)" />
          </div>
          <div v-if="profile?.country" :class="row">
            <MapPin :class="iconCls" />
            <span class="min-w-0 flex-1"><span class="block text-[15px]" dir="auto">{{ profile.country }}</span><span class="block text-sm text-gray-500 dark:text-gray-400">{{ t("people.about.country") }}</span></span>
            <AudienceSelect v-if="isSelf && privacy" field="country" :model-value="privacy.country ?? 'public'" :disabled="savingPrivacy === 'country'" @update:model-value="setAudience('country', $event)" />
          </div>
          <p v-if="!isSelf && !place" class="text-[15px] text-gray-500 dark:text-gray-400">{{ t("people.about.nothing") }}</p>
          <button v-if="isSelf" type="button" :class="addBtn" data-testid="about-edit-places" @click="startEdit('places')">
            <Plus class="h-6 w-6 rounded-full border-2 border-current p-0.5" /> {{ place ? t("people.about.editPlace") : t("people.about.addPlace") }}
          </button>
        </template>
      </div>

      <!-- Contact and basic info -->
      <div v-else-if="section === 'contact'">
        <div class="mb-2 flex items-center justify-between gap-2">
          <h3 class="text-[17px] font-bold">{{ t("people.about.links") }}</h3>
          <AudienceSelect v-if="isSelf && privacy" field="links" :model-value="privacy.links ?? 'public'" :disabled="savingPrivacy === 'links'" @update:model-value="setAudience('links', $event)" />
        </div>
        <ul>
          <li v-for="l in profile?.links ?? []" :key="l.id" :class="row" data-testid="about-link-item">
            <LinkIcon :class="iconCls" />
            <span class="min-w-0 flex-1">
              <a :href="l.url" target="_blank" rel="noopener noreferrer" class="block truncate text-[15px] font-medium text-brand-600 hover:underline dark:text-brand-300" dir="ltr">{{ linkHost(l.url) }}</a>
              <span v-if="l.label" class="block text-sm text-gray-500 dark:text-gray-400" dir="auto">{{ l.label }}</span>
            </span>
            <button v-if="isSelf" type="button" :class="delBtn" :aria-label="t('people.about.deleteItem', { name: l.label || linkHost(l.url) })" @click="dropLink(l.id)"><Trash2 class="h-4 w-4" /></button>
          </li>
        </ul>
        <p v-if="!isSelf && !profile?.links?.length" class="text-[15px] text-gray-500 dark:text-gray-400">{{ t("people.about.nothing") }}</p>
        <button v-if="isSelf && !addingLink" type="button" :class="addBtn" data-testid="about-add-link" @click="addingLink = true">
          <Plus class="h-6 w-6 rounded-full border-2 border-current p-0.5" /> {{ t("people.about.addLink") }}
        </button>
        <form v-if="isSelf && addingLink" class="mt-2 space-y-2 rounded-xl border border-gray-200 p-3 dark:border-gray-800" data-testid="about-link-form" @submit.prevent="saveLink">
          <input v-model="link.url" type="url" class="input" dir="ltr" :placeholder="t('people.about.url')" :aria-label="t('people.about.url')" required />
          <input v-model="link.label" class="input" dir="auto" :placeholder="t('people.about.label')" :aria-label="t('people.about.label')" maxlength="60" />
          <div class="flex justify-end gap-2">
            <button type="button" class="btn-ghost" @click="addingLink = false">{{ t("people.about.cancel") }}</button>
            <button type="submit" class="btn-primary" :disabled="!link.url.trim()">{{ t("people.about.save") }}</button>
          </div>
        </form>

        <h3 class="mb-2 mt-6 text-[17px] font-bold">{{ t("people.about.joined") }}</h3>
        <div v-if="profile?.created_at" :class="row">
          <CalendarDays :class="iconCls" />
          <span class="flex-1 text-[15px]">{{ joinedText(profile.created_at) }}</span>
        </div>
      </div>

      <!-- Details about you -->
      <div v-else>
        <form v-if="isSelf && editing === 'details'" class="space-y-2" data-testid="about-details-form" @submit.prevent="saveScalars">
          <label class="block text-sm font-semibold">{{ t("people.about.intro") }}
            <input v-model="scalars.intro" class="input mt-1" dir="auto" maxlength="160" />
          </label>
          <label class="block text-sm font-semibold">{{ t("people.about.bio") }}
            <textarea v-model="scalars.bio" class="input mt-1 min-h-24" dir="auto" rows="4" maxlength="300" />
          </label>
          <div class="flex justify-end gap-2">
            <button type="button" class="btn-ghost" @click="editing = ''">{{ t("people.about.cancel") }}</button>
            <button type="submit" class="btn-primary" :disabled="savingScalars">{{ t("people.about.save") }}</button>
          </div>
        </form>
        <template v-else>
          <div class="mb-2 flex items-center justify-between gap-2">
            <h3 class="text-[17px] font-bold">{{ t("people.about.intro") }}</h3>
            <AudienceSelect v-if="isSelf && privacy" field="intro" :model-value="privacy.intro ?? 'public'" :disabled="savingPrivacy === 'intro'" @update:model-value="setAudience('intro', $event)" />
          </div>
          <div :class="row">
            <UserRound :class="iconCls" />
            <p class="flex-1 text-[15px]" :class="profile?.intro ? '' : 'text-gray-500 dark:text-gray-400'" dir="auto">{{ profile?.intro || t("people.about.nothing") }}</p>
          </div>
          <div class="mb-2 mt-4 flex items-center justify-between gap-2">
            <h3 class="text-[17px] font-bold">{{ t("people.about.bio") }}</h3>
            <AudienceSelect v-if="isSelf && privacy" field="bio" :model-value="privacy.bio ?? 'public'" :disabled="savingPrivacy === 'bio'" @update:model-value="setAudience('bio', $event)" />
          </div>
          <div :class="row">
            <Quote :class="iconCls" />
            <p class="flex-1 whitespace-pre-line text-[15px]" :class="profile?.bio ? '' : 'text-gray-500 dark:text-gray-400'" dir="auto">{{ profile?.bio || t("people.about.nothing") }}</p>
          </div>
          <button v-if="isSelf" type="button" :class="addBtn" class="mt-2" data-testid="about-edit-details" @click="startEdit('details')">
            <Plus class="h-6 w-6 rounded-full border-2 border-current p-0.5" /> {{ t("people.about.editDetails") }}
          </button>
        </template>
      </div>
    </div>
  </section>
</template>
