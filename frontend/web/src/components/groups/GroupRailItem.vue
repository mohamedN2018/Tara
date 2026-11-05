<script setup lang="ts">
import { UsersRound } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { relativeTime } from "@/lib/format";
import { useMediaUrl } from "@/lib/useMediaUrl";
import { type Group, groupPath, isStaff } from "@/services/groups";

// One of "Your groups" in the groups side panel: the group's picture (its
// cover, as the group has no separate avatar), its name, and when it last had
// a post. `lastPostAt` is undefined while unknown (nothing shown), null when
// the group has no posts yet.
const props = defineProps<{ group: Group; lastPostAt?: string | null }>();
const { t } = useI18n();
const cover = useMediaUrl(() => props.group.cover_media_id);

const activity = computed(() => {
  if (props.lastPostAt === undefined) return "";
  if (props.lastPostAt === null) return t("socialShell.groups.noPostsYet");
  return t("socialShell.groups.lastActive", { time: relativeTime(props.lastPostAt) });
});
</script>

<template>
  <RouterLink :to="groupPath(group)" class="nav-item items-center" data-testid="groups-rail-item">
    <span class="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-tara-gradient text-white">
      <img v-if="cover" :src="cover" alt="" class="h-full w-full object-cover" loading="lazy" decoding="async" />
      <UsersRound v-else class="h-5 w-5" aria-hidden="true" />
    </span>
    <span class="min-w-0 flex-1 text-start">
      <span class="block truncate text-sm font-semibold"><bdi>{{ group.name }}</bdi></span>
      <span v-if="activity" class="block truncate text-xs font-normal text-gray-600 dark:text-gray-400" data-testid="groups-rail-activity">{{ activity }}</span>
    </span>
    <span v-if="isStaff(group.viewer.role)" class="shrink-0 text-[10px] text-gray-600 dark:text-gray-400">{{ t(`groups.roles.${group.viewer.role}`) }}</span>
  </RouterLink>
</template>
