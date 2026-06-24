<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { graphService } from "@/services/graph";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";

const { t } = useI18n();
const route = useRoute();
const directory = useDirectoryStore();
const presence = usePresenceStore();

type Tab = "followers" | "following" | "blocked";
const TABS: Tab[] = ["followers", "following", "blocked"];
const tab = ref<Tab>((route.query.tab as Tab) || "followers");

const ids = ref<string[]>([]);
const loading = ref(true);
const loaded = ref<Record<Tab, string[] | null>>({ followers: null, following: null, blocked: null });
const unblocking = ref("");

async function fetchTab(tb: Tab): Promise<string[]> {
  if (tb === "followers") return graphService.followerIds();
  if (tb === "following") return graphService.followingIds();
  return graphService.blockedIds();
}

async function load(tb: Tab) {
  loading.value = true;
  try {
    if (!loaded.value[tb]) loaded.value[tb] = await fetchTab(tb).catch(() => []);
    ids.value = loaded.value[tb] ?? [];
  } finally {
    loading.value = false;
  }
}

function switchTab(tb: Tab) {
  if (tab.value === tb) return;
  tab.value = tb;
  load(tb);
}

async function unblock(id: string) {
  if (unblocking.value) return;
  unblocking.value = id;
  try {
    await graphService.unblock(id);
    loaded.value.blocked = (loaded.value.blocked ?? []).filter((x) => x !== id);
    if (tab.value === "blocked") ids.value = loaded.value.blocked;
  } catch {
    /* ignore */
  } finally {
    unblocking.value = "";
  }
}

onMounted(() => load(tab.value));
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[600px]">
      <h1 class="mb-4 text-xl font-bold">{{ t("connections.title") }}</h1>

      <div class="mb-4 flex gap-1 rounded-xl bg-gray-100 p-1 text-sm dark:bg-gray-800">
        <button
          v-for="tb in TABS"
          :key="tb"
          class="flex-1 rounded-lg py-1.5 font-medium transition"
          :class="tab === tb ? 'bg-white text-brand-600 shadow-sm dark:bg-gray-900' : 'text-gray-500'"
          @click="switchTab(tb)"
        >
          {{ t(`connections.${tb}`) }}
        </button>
      </div>

      <LoadingSkeleton v-if="loading" :rows="4" />
      <EmptyState v-else-if="ids.length === 0">
        {{ tab === "followers" ? t("connections.noFollowers") : tab === "following" ? t("connections.noFollowing") : t("connections.noBlocked") }}
      </EmptyState>
      <ul v-else class="space-y-2">
        <li v-for="id in ids" :key="id" class="card flex items-center gap-3 p-3">
          <RouterLink :to="{ name: 'profile-by-id', params: { id } }" class="relative shrink-0">
            <UserAvatar :name="directory.nameOf(id) || id" :size="44" />
            <span
              v-if="presence.isOnline(id)"
              class="absolute -end-0.5 -bottom-0.5 h-3 w-3 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
            />
          </RouterLink>
          <RouterLink :to="{ name: 'profile-by-id', params: { id } }" class="min-w-0 flex-1 truncate text-sm font-medium hover:underline">
            {{ directory.label(id, 16) }}
          </RouterLink>
          <button
            v-if="tab === 'blocked'"
            class="btn-ghost text-sm"
            :disabled="unblocking === id"
            @click="unblock(id)"
          >
            {{ t("connections.unblock") }}
          </button>
        </li>
      </ul>
    </div>
  </AppShell>
</template>
