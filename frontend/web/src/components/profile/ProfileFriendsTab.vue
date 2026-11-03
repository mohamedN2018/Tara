<script setup lang="ts">
import { toRefs } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import type { ProfileState } from "@/lib/useProfile";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";

const props = defineProps<{ state: ProfileState }>();

const { friendsCount, relFriendIds } = toRefs(props.state);
const { t } = useI18n();
const directory = useDirectoryStore();
const presence = usePresenceStore();
</script>

<template>
  <div class="card p-4">
    <h2 class="mb-3 flex items-center justify-between text-base font-bold">
      <span>{{ t("profile.friends") }}</span>
      <span v-if="friendsCount !== null" class="text-sm font-normal text-gray-400">{{ friendsCount }}</span>
    </h2>
    <EmptyState v-if="relFriendIds.length === 0">{{ t("friends.none") }}</EmptyState>
    <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <RouterLink
        v-for="id in relFriendIds.slice(0, 30)"
        :key="id"
        :to="{ name: 'profile-by-id', params: { id } }"
        class="flex flex-col items-center gap-2 rounded-xl p-3 text-center transition hover:bg-gray-100 dark:hover:bg-gray-800"
      >
        <span class="relative">
          <UserAvatar :name="directory.label(id)" :media-id="directory.avatarOf(id)" :size="56" />
          <span
            v-if="presence.isOnline(id)"
            class="absolute -end-0.5 -bottom-0.5 h-3 w-3 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
          />
        </span>
        <span class="truncate text-xs font-medium" dir="auto">{{ directory.label(id) }}</span>
      </RouterLink>
    </div>
  </div>
</template>
