<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import FriendButton from "@/components/social/FriendButton.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { type FriendRequest, graphService } from "@/services/graph";

const { t } = useI18n();

const tab = ref<"requests" | "all">("requests");
const requests = ref<FriendRequest[]>([]);
const friendIds = ref<string[]>([]);
const loading = ref(true);

async function load() {
  loading.value = true;
  try {
    [requests.value, friendIds.value] = await Promise.all([
      graphService.incomingRequests().catch(() => []),
      graphService.friends().catch(() => []),
    ]);
  } finally {
    loading.value = false;
  }
}

function onResolved(id: string) {
  requests.value = requests.value.filter((r) => r.id !== id);
}

onMounted(load);
</script>

<template>
  <AppShell>
    <h1 class="mb-4 text-xl font-bold">{{ t("friends.title") }}</h1>

    <div class="mb-4 flex gap-2 border-b border-gray-200 dark:border-gray-800">
      <button
        class="border-b-2 px-3 py-2 text-sm font-medium transition"
        :class="tab === 'requests' ? 'border-brand-600 text-brand-600' : 'border-transparent text-gray-500'"
        @click="tab = 'requests'"
      >
        {{ t("friends.requests") }}
        <span v-if="requests.length" class="ms-1 rounded-full bg-red-500 px-1.5 text-xs text-white">
          {{ requests.length }}
        </span>
      </button>
      <button
        class="border-b-2 px-3 py-2 text-sm font-medium transition"
        :class="tab === 'all' ? 'border-brand-600 text-brand-600' : 'border-transparent text-gray-500'"
        @click="tab = 'all'"
      >
        {{ t("friends.all") }}
      </button>
    </div>

    <LoadingSkeleton v-if="loading" :rows="3" />

    <template v-else-if="tab === 'requests'">
      <EmptyState v-if="requests.length === 0">{{ t("friends.noRequests") }}</EmptyState>
      <ul v-else class="space-y-2">
        <li v-for="r in requests" :key="r.id" class="card flex items-center gap-3 p-3">
          <UserAvatar :name="r.from_user_id" />
          <span class="flex-1 truncate text-sm font-medium">{{ r.from_user_id.slice(0, 12) }}</span>
          <FriendButton
            :user-id="r.from_user_id"
            :request-id="r.id"
            state="pending_in"
            @click="onResolved(r.id)"
          />
        </li>
      </ul>
    </template>

    <template v-else>
      <EmptyState v-if="friendIds.length === 0">{{ t("feed.empty") }}</EmptyState>
      <ul v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <li v-for="id in friendIds" :key="id" class="card flex flex-col items-center gap-2 p-4">
          <UserAvatar :name="id" :size="56" />
          <span class="truncate text-sm font-medium">{{ id.slice(0, 10) }}</span>
        </li>
      </ul>
    </template>
  </AppShell>
</template>
