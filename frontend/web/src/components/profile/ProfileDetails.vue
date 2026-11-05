<script setup lang="ts">
import { Briefcase, CalendarDays, GraduationCap, Home, LinkIcon } from "lucide-vue-next";
import { computed, toRefs } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { educationHeadline, educationRange, linkHost, sameText, workHeadline, workRange } from "@/lib/profileFormat";
import type { ProfileState } from "@/lib/useProfile";
import { useDirectoryStore } from "@/stores/directory";

// The Posts tab's start column (reference 3.png): Intro card, Photos card and
// Friends card, each with a "see all" into its own tab.
const props = defineProps<{ state: ProfileState }>();
defineEmits<{ edit: []; "open-photo": [src: string] }>();

const { profile, hasAbout, isSelf, photoUrls, relFriendIds, friendsCount, mutual, displayName, joinedText } = toRefs(
  props.state,
);

const { t, locale } = useI18n();
const directory = useDirectoryStore();
// The bio repeats under the intro only when it says something else.
const showBio = computed(() => !!profile.value?.bio && !sameText(profile.value.bio, profile.value.intro));
const place = computed(() => [profile.value?.city, profile.value?.country].filter(Boolean).join(", "));

function go(tab: "about" | "photos" | "friends") {
  props.state.openTab(tab, tab === "friends" ? "all" : undefined);
}
</script>

<template>
  <div class="space-y-4 lg:sticky lg:top-20">
    <!-- Intro -->
    <section v-if="hasAbout || isSelf" class="card p-4" data-testid="intro-card">
      <h2 class="mb-3 text-xl font-bold">{{ t("people.intro.title") }}</h2>
      <template v-if="hasAbout">
        <p v-if="profile?.intro" class="mb-1 text-center text-[15px] font-semibold text-gray-800 dark:text-gray-100" dir="auto">{{ profile.intro }}</p>
        <p v-if="showBio" class="mb-3 whitespace-pre-line text-center text-[15px] text-gray-700 dark:text-gray-200" dir="auto">{{ profile?.bio }}</p>
        <ul class="space-y-3 text-[15px]">
          <li v-for="w in profile?.work ?? []" :key="`w${w.id}`" class="flex items-start gap-3">
            <Briefcase class="mt-0.5 h-5 w-5 shrink-0 text-gray-500 dark:text-gray-400" />
            <span class="min-w-0">
              <span class="block" dir="auto">{{ workHeadline(w, t) }}</span>
              <span v-if="workRange(w, t, locale)" class="block text-xs text-gray-500 dark:text-gray-400">{{ workRange(w, t, locale) }}</span>
            </span>
          </li>
          <li v-for="e in profile?.education ?? []" :key="`e${e.id}`" class="flex items-start gap-3">
            <GraduationCap class="mt-0.5 h-5 w-5 shrink-0 text-gray-500 dark:text-gray-400" />
            <span class="min-w-0">
              <span class="block" dir="auto">{{ educationHeadline(e, t) }}<template v-if="e.degree"> · {{ e.degree }}</template></span>
              <span v-if="educationRange(e, t)" class="block text-xs text-gray-500 dark:text-gray-400">{{ educationRange(e, t) }}</span>
            </span>
          </li>
          <li v-if="place" class="flex items-center gap-3">
            <Home class="h-5 w-5 shrink-0 text-gray-500 dark:text-gray-400" />
            <span dir="auto">{{ t("people.intro.livesIn", { place }) }}</span>
          </li>
          <li v-if="profile?.links?.length" class="flex items-start gap-3">
            <LinkIcon class="mt-0.5 h-5 w-5 shrink-0 text-gray-500 dark:text-gray-400" />
            <span class="flex min-w-0 flex-wrap gap-x-1">
              <template v-for="(l, i) in profile.links" :key="l.id">
                <a :href="l.url" target="_blank" rel="noopener noreferrer" class="truncate font-medium text-brand-600 hover:underline dark:text-brand-300" dir="auto">{{ l.label || linkHost(l.url) }}</a>
                <span v-if="i < profile.links.length - 1" aria-hidden="true">·</span>
              </template>
            </span>
          </li>
          <li v-if="profile?.created_at" class="flex items-center gap-3">
            <CalendarDays class="h-5 w-5 shrink-0 text-gray-500 dark:text-gray-400" />
            <span>{{ joinedText(profile.created_at) }}</span>
          </li>
        </ul>
      </template>
      <p v-else class="text-sm text-gray-500 dark:text-gray-400">{{ t("profile.limitedInfo") }}</p>
      <button v-if="isSelf" type="button" class="btn mt-4 w-full bg-gray-100 text-gray-900 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700" data-testid="intro-edit-details" @click="go('about')">
        {{ t("people.intro.editDetails") }}
      </button>
    </section>

    <!-- Photos -->
    <section v-if="photoUrls.length" class="card p-4">
      <div class="mb-3 flex items-center justify-between">
        <h2 class="text-xl font-bold">{{ t("profile.photos") }}</h2>
        <button type="button" class="rounded-md px-2 py-1 text-[15px] text-brand-600 hover:bg-brand-50 dark:text-brand-300 dark:hover:bg-brand-950/40" @click="go('photos')">{{ t("people.friendsHub.seeAll") }}</button>
      </div>
      <div class="grid grid-cols-3 gap-1 overflow-hidden rounded-lg">
        <button
          v-for="(src, i) in photoUrls.slice(0, 9)"
          :key="i"
          type="button"
          class="aspect-square overflow-hidden bg-gray-100 transition hover:opacity-90 dark:bg-gray-800"
          @click="$emit('open-photo', src)"
        >
          <img :src="src" class="h-full w-full object-cover" loading="lazy" decoding="async" :alt="t('profile.photoAlt', { n: i + 1, name: displayName })" />
        </button>
      </div>
    </section>

    <!-- Friends -->
    <section v-if="relFriendIds.length" class="card p-4">
      <div class="mb-1 flex items-start justify-between">
        <div>
          <h2 class="text-xl font-bold">{{ t("profile.friends") }}</h2>
          <p class="text-[15px] text-gray-500 dark:text-gray-400">
            {{ t("people.hero.friends", friendsCount ?? relFriendIds.length) }}<template v-if="!isSelf && mutual.length"> · {{ t("people.hero.mutual", mutual.length) }}</template>
          </p>
        </div>
        <button type="button" class="rounded-md px-2 py-1 text-[15px] text-brand-600 hover:bg-brand-50 dark:text-brand-300 dark:hover:bg-brand-950/40" @click="go('friends')">{{ t("people.friendsHub.seeAll") }}</button>
      </div>
      <div class="mt-3 grid grid-cols-3 gap-x-2 gap-y-3">
        <RouterLink
          v-for="id in relFriendIds.slice(0, 9)"
          :key="id"
          :to="{ name: 'profile-by-id', params: { id } }"
          class="group min-w-0"
        >
          <UserAvatar :name="directory.label(id)" :media-id="directory.avatarOf(id)" :size="104" class="aspect-square !h-auto !w-full !rounded-lg" />
          <span class="mt-1 block truncate text-[13px] font-semibold group-hover:underline" dir="auto">{{ directory.label(id) }}</span>
        </RouterLink>
      </div>
    </section>
  </div>
</template>
