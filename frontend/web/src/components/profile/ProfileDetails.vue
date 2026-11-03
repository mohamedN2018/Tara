<script setup lang="ts">
import { Briefcase, CalendarDays, GraduationCap, LinkIcon, MapPin } from "lucide-vue-next";
import { toRefs } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import type { ProfileState } from "@/lib/useProfile";
import { useDirectoryStore } from "@/stores/directory";

const props = defineProps<{ state: ProfileState }>();
defineEmits<{ edit: []; "open-photo": [src: string] }>();

const { profile, hasAbout, isSelf, photoUrls, relFriendIds, friendsCount, displayName, joinedText, tab } =
  toRefs(props.state);

const { t } = useI18n();
const directory = useDirectoryStore();
</script>

<template>
  <div class="space-y-4 xl:sticky xl:top-20">
    <!-- Intro / About (full) -->
    <div v-if="hasAbout || isSelf" class="card p-4">
      <div class="mb-3 flex items-center justify-between">
        <h3 class="text-base font-bold">{{ t("profile.intro") }}</h3>
        <button v-if="isSelf" class="text-xs font-medium text-brand-600" @click="$emit('edit')">
          {{ t("profile.editProfile") }}
        </button>
      </div>
      <div v-if="hasAbout" class="space-y-3 text-sm">
        <p v-if="profile?.intro" class="font-medium text-gray-700 dark:text-gray-200" dir="auto">{{ profile.intro }}</p>
        <p v-if="profile?.bio" class="whitespace-pre-line text-gray-600 dark:text-gray-300" dir="auto">{{ profile.bio }}</p>
        <div v-if="profile?.work?.length" class="space-y-1.5">
          <p v-for="w in profile.work" :key="w.id" class="flex items-start gap-2 text-gray-600 dark:text-gray-300">
            <Briefcase class="mt-0.5 h-4 w-4 shrink-0 text-gray-400" />
            <span>
              <span class="font-medium" dir="auto">{{ w.title || "—" }}</span><span v-if="w.company" dir="auto"> · {{ w.company }}</span><span v-if="w.is_current" class="text-xs text-brand-600"> ({{ t("profile.present") }})</span>
            </span>
          </p>
        </div>
        <div v-if="profile?.education?.length" class="space-y-1.5">
          <p v-for="e in profile.education" :key="e.id" class="flex items-start gap-2 text-gray-600 dark:text-gray-300">
            <GraduationCap class="mt-0.5 h-4 w-4 shrink-0 text-gray-400" />
            <span>
              <span class="font-medium" dir="auto">{{ e.school }}</span><span v-if="e.field" dir="auto"> · {{ e.field }}</span><span v-if="e.start_year || e.end_year" class="text-xs text-gray-400"> ({{ e.start_year || "?" }}–{{ e.end_year || t("profile.present") }})</span>
            </span>
          </p>
        </div>
        <div v-if="profile?.links?.length" class="space-y-1.5">
          <a v-for="l in profile.links" :key="l.id" :href="l.url" target="_blank" rel="noopener noreferrer" class="flex items-center gap-2 text-brand-600 hover:underline">
            <LinkIcon class="h-4 w-4 shrink-0" /> <span class="truncate" dir="auto">{{ l.label || l.url }}</span>
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
          @click="$emit('open-photo', src)"
        >
          <img :src="src" class="h-full w-full object-cover" loading="lazy" decoding="async" :alt="t('profile.photoAlt', { n: i + 1, name: displayName })" />
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
          <UserAvatar :name="directory.label(id)" :media-id="directory.avatarOf(id)" :size="56" />
          <span class="w-full truncate text-center text-[11px] text-gray-600 dark:text-gray-300" dir="auto">{{ directory.label(id) }}</span>
        </RouterLink>
      </div>
    </div>
  </div>
</template>
