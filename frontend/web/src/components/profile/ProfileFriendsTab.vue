<script setup lang="ts">
import { Flag } from "lucide-vue-next";
import { computed, ref, toRefs, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { api } from "@/lib/api";
import type { FriendsList, ProfileState } from "@/lib/useProfile";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";
import type { Page } from "@/services/pages";

// Friends tab with Facebook-style sub-lists: all friends, mutual friends,
// followers and following (people and pages). A list the owner's graph privacy
// hides (server 404) is left out entirely.
const props = defineProps<{ state: ProfileState }>();

const { friendsCount, relFriendIds, friendsHidden, mutual, isSelf, followerList, followingList, friendsList } = toRefs(
  props.state,
);
const { t } = useI18n();
const directory = useDirectoryStore();
const presence = usePresenceStore();

const lists = computed<FriendsList[]>(() => {
  const out: FriendsList[] = [];
  if (!friendsHidden.value) out.push("all");
  if (!isSelf.value && !friendsHidden.value && mutual.value.length) out.push("mutual");
  // A follow list shows once it has loaded (or failed, with a retry). While loading it shows only
  // when it is the one asked for, so a deep link waits instead of falling back.
  const shows = (v: unknown, l: FriendsList) => (v === null ? friendsList.value === l : v !== "hidden");
  if (shows(followerList.value, "followers")) out.push("followers");
  if (shows(followingList.value, "following")) out.push("following");
  return out;
});
// A deep link to a hidden list falls back to the first visible one.
watch(
  lists,
  (ls) => {
    if (ls.length && !ls.includes(friendsList.value)) props.state.setFriendsList(ls[0]);
  },
  { immediate: true },
);

const people = computed<string[] | null>(() => {
  switch (friendsList.value) {
    case "all":
      return relFriendIds.value;
    case "mutual":
      return mutual.value;
    case "followers":
      return Array.isArray(followerList.value) ? followerList.value : null;
    case "following":
      return Array.isArray(followingList.value)
        ? followingList.value.filter((f) => f.target_type === "user").map((f) => f.target_id)
        : null;
  }
  return null;
});

// Followed pages: names and handles come from the page itself (GET /pages/id/<id>/).
const pageCards = ref<Page[]>([]);
watch(
  followingList,
  async (rows) => {
    if (!Array.isArray(rows)) return;
    const ids = rows.filter((r) => r.target_type === "page").map((r) => r.target_id).slice(0, 30);
    const loaded = await Promise.all(
      ids.map((id) =>
        api
          .get<{ data: Page }>(`/pages/id/${id}/`)
          .then((r) => r.data.data)
          .catch(() => null),
      ),
    );
    pageCards.value = loaded.filter((p): p is Page => !!p);
  },
  { immediate: true },
);

const failed = computed(
  () =>
    (friendsList.value === "followers" && followerList.value === "error") ||
    (friendsList.value === "following" && followingList.value === "error"),
);

const count = (l: FriendsList) =>
  l === "all"
    ? (friendsCount.value ?? relFriendIds.value.length)
    : l === "mutual"
      ? mutual.value.length
      : null;
</script>

<template>
  <section class="card p-4" data-testid="profile-friends-tab">
    <div class="mb-2 flex items-center justify-between gap-2">
      <h2 class="text-xl font-bold">{{ t("profile.friends") }}</h2>
      <RouterLink
        v-if="isSelf"
        to="/settings/privacy#relationships"
        class="btn-ghost text-sm font-semibold text-brand-700 dark:text-brand-300"
        data-testid="friends-edit-privacy"
      >
        {{ t("people.hero.privacy") }}
      </RouterLink>
    </div>
    <EmptyState v-if="!lists.length">{{ t("people.friendsTab.hidden") }}</EmptyState>
    <template v-else>
      <nav class="mb-4 flex gap-1 overflow-x-auto border-b border-gray-200 dark:border-gray-800" :aria-label="t('people.friendsTab.nav')" role="tablist">
        <button
          v-for="l in lists"
          :key="l"
          type="button"
          role="tab"
          :aria-selected="friendsList === l"
          :data-testid="`friends-list-${l}`"
          class="relative whitespace-nowrap px-3 py-3 text-[15px] font-semibold transition"
          :class="
            friendsList === l
              ? 'text-brand-600 after:absolute after:inset-x-1 after:bottom-0 after:h-[3px] after:rounded-full after:bg-brand-600 dark:text-brand-300'
              : 'rounded-lg text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'
          "
          @click="state.setFriendsList(l)"
        >
          {{ t(`people.friendsTab.${l}`) }}
          <span v-if="count(l) !== null" class="ms-1 text-sm font-normal text-gray-500 dark:text-gray-400">{{ count(l) }}</span>
        </button>
      </nav>

      <ErrorState v-if="failed" @retry="state.loadFollowLists(true)" />
      <LoadingSkeleton v-else-if="people === null" :rows="2" />
      <template v-else>
        <EmptyState v-if="people.length === 0 && !(friendsList === 'following' && pageCards.length)">{{ t("people.friendsTab.empty") }}</EmptyState>
        <ul v-else class="grid grid-cols-1 gap-2 sm:grid-cols-2" data-testid="friends-list">
          <li v-for="id in people.slice(0, 200)" :key="id">
            <RouterLink
              :to="{ name: 'profile-by-id', params: { id } }"
              class="flex items-center gap-3 rounded-xl border border-gray-200 p-3 transition hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-800/60"
            >
              <span class="relative shrink-0">
                <UserAvatar :name="directory.label(id)" :media-id="directory.avatarOf(id)" :size="72" class="!rounded-lg" />
                <span
                  v-if="presence.isOnline(id)"
                  class="absolute -end-0.5 -bottom-0.5 h-3.5 w-3.5 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
                />
              </span>
              <span class="min-w-0 truncate text-[15px] font-semibold" dir="auto">{{ directory.label(id) }}</span>
            </RouterLink>
          </li>
          <template v-if="friendsList === 'following'">
            <li v-for="pg in pageCards" :key="pg.id">
              <RouterLink
                :to="{ name: 'page', params: { handle: pg.handle } }"
                class="flex items-center gap-3 rounded-xl border border-gray-200 p-3 transition hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-800/60"
              >
                <UserAvatar :name="pg.name" :media-id="pg.avatar_media_id" :size="72" class="!rounded-lg" />
                <span class="min-w-0">
                  <span class="block truncate text-[15px] font-semibold"><bdi>{{ pg.name }}</bdi></span>
                  <span class="inline-flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400"><Flag class="h-3 w-3" />{{ t("people.friendsTab.pages") }}</span>
                </span>
              </RouterLink>
            </li>
          </template>
        </ul>
      </template>
    </template>
  </section>
</template>
