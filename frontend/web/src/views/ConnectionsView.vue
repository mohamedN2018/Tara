<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { blockedAvatar, blockedLabel, loadBlockedCards } from "@/lib/blockedCards";
import { type PrefKind, useRelationshipPrefs } from "@/lib/useRelationshipPrefs";
import { graphService } from "@/services/graph";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";
import { useToastStore } from "@/stores/toasts";

// Followers, following and the owner-private lists (blocked, muted,
// restricted, favorites). The tab lives in ?tab= so the privacy center and
// menus can deep-link to one list.
const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const directory = useDirectoryStore();
const presence = usePresenceStore();
const toasts = useToastStore();
const prefs = useRelationshipPrefs();

type Tab = "followers" | "following" | "blocked" | "muted" | "restricted" | "favorites";
const TABS: Tab[] = ["followers", "following", "favorites", "muted", "restricted", "blocked"];
// Owner-private lists map onto the shared relationship-prefs store.
const PREF: Partial<Record<Tab, PrefKind>> = { blocked: "blocks", muted: "mutes", restricted: "restricted", favorites: "favorites" };
const LABEL: Record<Tab, string> = {
  followers: "connections.followers",
  following: "connections.following",
  blocked: "connections.blocked",
  muted: "people.connections.muted",
  restricted: "people.connections.restricted",
  favorites: "people.connections.favorites",
};
const EMPTY: Record<Tab, string> = {
  followers: "connections.noFollowers",
  following: "connections.noFollowing",
  blocked: "connections.noBlocked",
  muted: "people.connections.noMuted",
  restricted: "people.connections.noRestricted",
  favorites: "people.connections.noFavorites",
};
const REMOVE: Partial<Record<Tab, string>> = {
  blocked: "connections.unblock",
  muted: "people.connections.unmute",
  restricted: "people.connections.unrestrict",
  favorites: "people.connections.unfavorite",
};
const fromQuery = (v: unknown): Tab => (TABS.includes(v as Tab) ? (v as Tab) : "followers");
const tab = ref<Tab>(fromQuery(route.query.tab));

const ids = ref<string[]>([]);
const loading = ref(true);
const error = ref(false);
const graphLists = ref<Partial<Record<Tab, string[]>>>({});
const removing = ref("");

async function load(tb: Tab) {
  loading.value = true;
  error.value = false;
  try {
    const kind = PREF[tb];
    if (kind) {
      await prefs.ensure([kind]);
      if (!prefs.loaded(kind)) throw new Error("unavailable");
      ids.value = prefs.list(kind);
      if (kind === "blocks") await loadBlockedCards(ids.value);
    } else {
      graphLists.value[tb] ??= await (tb === "followers" ? graphService.followerIds() : graphService.followingIds());
      ids.value = graphLists.value[tb] ?? [];
    }
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

function switchTab(tb: Tab) {
  if (tab.value === tb) return;
  tab.value = tb;
  void router.replace({ query: { ...route.query, tab: tb === "followers" ? undefined : tb } });
  void load(tb);
}
watch(
  () => route.query.tab,
  (v) => {
    const next = fromQuery(v);
    if (next !== tab.value) {
      tab.value = next;
      void load(next);
    }
  },
);

async function remove(id: string) {
  const kind = PREF[tab.value];
  if (!kind || removing.value) return;
  removing.value = id;
  try {
    await prefs.set(kind, id, false);
    ids.value = ids.value.filter((x) => x !== id);
  } catch (e) {
    toasts.error(e);
  } finally {
    removing.value = "";
  }
}

onMounted(() => load(tab.value));
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[680px]">
      <h1 class="mb-4 text-xl font-bold">{{ t("connections.title") }}</h1>

      <div class="mb-4 flex gap-1 overflow-x-auto rounded-xl bg-gray-100 p-1 text-sm dark:bg-gray-800" role="tablist" :aria-label="t('people.connections.tabs')">
        <button
          v-for="tb in TABS"
          :key="tb"
          type="button"
          role="tab"
          :aria-selected="tab === tb"
          class="shrink-0 grow rounded-lg px-3 py-1.5 font-medium transition"
          :class="tab === tb ? 'bg-white text-brand-600 shadow-sm dark:bg-gray-900 dark:text-brand-300' : 'text-gray-600 dark:text-gray-300'"
          :data-testid="`connections-tab-${tb}`"
          @click="switchTab(tb)"
        >
          {{ t(LABEL[tb]) }}
        </button>
      </div>

      <!-- The same lists live under Settings > Feed and content preferences; link there, don't duplicate. -->
      <RouterLink
        v-if="PREF[tab]"
        :to="`/settings/content#${PREF[tab]}`"
        class="mb-3 inline-flex text-sm font-semibold text-brand-700 hover:underline dark:text-brand-300"
        data-testid="connections-settings-link"
      >
        {{ t("people.connections.manageInSettings") }}
      </RouterLink>

      <LoadingSkeleton v-if="loading" :rows="4" />
      <ErrorState v-else-if="error" @retry="load(tab)" />
      <EmptyState v-else-if="ids.length === 0" class="card">{{ t(EMPTY[tab]) }}</EmptyState>
      <ul v-else class="space-y-2" :data-testid="`connections-list-${tab}`">
        <li v-for="id in ids" :key="id" class="card flex items-center gap-3 p-3">
          <!-- Blocked people: named from the owner's own block list, no profile link (it's a 404). -->
          <template v-if="tab === 'blocked'">
            <UserAvatar :name="blockedLabel(id)" :media-id="blockedAvatar(id)" :size="44" class="shrink-0" />
            <span class="min-w-0 flex-1 truncate text-sm font-medium" dir="auto" data-testid="connections-blocked-name">{{ blockedLabel(id) }}</span>
          </template>
          <template v-else>
            <RouterLink :to="{ name: 'profile-by-id', params: { id } }" class="relative shrink-0" tabindex="-1" aria-hidden="true">
              <UserAvatar :name="directory.label(id)" :media-id="directory.avatarOf(id)" :size="44" />
              <span
                v-if="presence.isOnline(id)"
                class="absolute -bottom-0.5 -end-0.5 h-3 w-3 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
              />
            </RouterLink>
            <RouterLink :to="{ name: 'profile-by-id', params: { id } }" class="min-w-0 flex-1 truncate text-sm font-medium hover:underline" dir="auto">
              {{ directory.label(id) }}
            </RouterLink>
          </template>
          <button v-if="REMOVE[tab]" type="button" class="btn-ghost text-sm" :disabled="removing === id" @click="remove(id)">
            {{ t(REMOVE[tab]!) }}
          </button>
        </li>
      </ul>
    </div>
  </AppShell>
</template>
