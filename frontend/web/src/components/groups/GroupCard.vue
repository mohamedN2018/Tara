<script setup lang="ts">
import { UsersRound, X } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useMediaUrl } from "@/lib/useMediaUrl";
import { type Group, groupPath } from "@/services/groups";
import { useDirectoryStore } from "@/stores/directory";

import PrivacyBadge from "./PrivacyBadge.vue";

// One group in a list: cover, name, privacy and size. Suggestions also say how
// many friends are members, and can be dismissed.
const props = withDefaults(defineProps<{ group: Group; dismissible?: boolean; compact?: boolean }>(), {
  dismissible: false,
  compact: false,
});
const emit = defineEmits<{ dismiss: [id: string] }>();

const { t } = useI18n();
const directory = useDirectoryStore();
const cover = useMediaUrl(() => props.group.cover_media_id);
const friendLine = computed(() => {
  const count = props.group.friend_member_count ?? 0;
  if (!count) return "";
  const first = props.group.friend_ids?.[0];
  if (!first) return t("groups.card.friends", { count }, count);
  const name = directory.label(first);
  return count === 1
    ? t("groups.card.friendOnly", { name })
    : t("groups.card.friendsNamed", { name, count: count - 1 }, count - 1);
});
</script>

<template>
  <article class="card card-hover relative overflow-hidden" :class="compact ? 'flex items-center gap-3 p-2' : ''">
    <RouterLink
      :to="groupPath(group)"
      class="block"
      :class="compact ? 'h-14 w-14 shrink-0 overflow-hidden rounded-xl' : 'h-28'"
      :aria-label="group.name"
      tabindex="-1"
    >
      <img v-if="cover" :src="cover" alt="" class="h-full w-full object-cover" />
      <span v-else class="flex h-full w-full items-center justify-center bg-tara-gradient text-white">
        <UsersRound class="h-7 w-7" aria-hidden="true" />
      </span>
    </RouterLink>
    <div :class="compact ? 'min-w-0 flex-1' : 'space-y-1 p-3'">
      <RouterLink :to="groupPath(group)" class="block truncate font-bold hover:text-brand-600 dark:hover:text-brand-300" data-testid="group-card-name">
        <bdi>{{ group.name }}</bdi>
      </RouterLink>
      <p class="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-gray-500 dark:text-gray-400">
        <PrivacyBadge :privacy="group.privacy" />
        <span aria-hidden="true">·</span>
        <span>{{ t("groups.memberCount", { count: group.member_count }, group.member_count) }}</span>
      </p>
      <p v-if="friendLine" class="truncate text-xs text-brand-700 dark:text-brand-300" dir="auto">{{ friendLine }}</p>
      <div v-if="$slots.actions" class="flex flex-wrap items-center gap-2 pt-2">
        <slot name="actions" />
      </div>
    </div>
    <button
      v-if="dismissible"
      type="button"
      class="absolute end-2 top-2 rounded-full bg-gray-950/50 p-1 text-white transition hover:bg-gray-950/70"
      :aria-label="t('groups.suggestions.dismiss', { name: group.name })"
      @click="emit('dismiss', group.id)"
    >
      <X class="h-4 w-4" aria-hidden="true" />
    </button>
  </article>
</template>
