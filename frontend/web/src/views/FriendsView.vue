<script setup lang="ts">
import { MessageCircle } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import FriendButton from "@/components/social/FriendButton.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { chatService } from "@/services/chat";
import { type FriendRequest, graphService } from "@/services/graph";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";

const { t } = useI18n();
const router = useRouter();
const presence = usePresenceStore();
const directory = useDirectoryStore();

const tab = ref<"requests" | "sent" | "all">("requests");
const requests = ref<FriendRequest[]>([]);
const sent = ref<FriendRequest[]>([]);
const friendIds = ref<string[]>([]);
const loading = ref(true);
const opening = ref("");
const cancelling = ref("");

async function load() {
  loading.value = true;
  try {
    [requests.value, sent.value, friendIds.value] = await Promise.all([
      graphService.incomingRequests().catch(() => [] as FriendRequest[]),
      graphService.outgoingRequests().catch(() => [] as FriendRequest[]),
      graphService.friends().catch(() => [] as string[]),
    ]);
  } finally {
    loading.value = false;
  }
}

function onResolved(id: string) {
  requests.value = requests.value.filter((r) => r.id !== id);
}

async function cancelRequest(id: string) {
  if (cancelling.value) return;
  cancelling.value = id;
  try {
    await graphService.declineFriendRequest(id);
    sent.value = sent.value.filter((r) => r.id !== id);
  } catch {
    // Request may already be resolved.
  } finally {
    cancelling.value = "";
  }
}

async function openChat(friendId: string) {
  if (opening.value) return;
  opening.value = friendId;
  try {
    const convo = await chatService.openDm(friendId);
    router.push(`/messages/${convo.id}`);
  } catch {
    // Conversation service may be unavailable.
  } finally {
    opening.value = "";
  }
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
        :class="tab === 'sent' ? 'border-brand-600 text-brand-600' : 'border-transparent text-gray-500'"
        @click="tab = 'sent'"
      >
        {{ t("friends.sent") }}
        <span v-if="sent.length" class="ms-1 rounded-full bg-gray-300 px-1.5 text-xs text-gray-700 dark:bg-gray-700 dark:text-gray-200">
          {{ sent.length }}
        </span>
      </button>
      <button
        class="border-b-2 px-3 py-2 text-sm font-medium transition"
        :class="tab === 'all' ? 'border-brand-600 text-brand-600' : 'border-transparent text-gray-500'"
        @click="tab = 'all'"
      >
        {{ t("friends.all") }}
        <span v-if="friendIds.length" class="ms-1 text-xs text-gray-400">{{ friendIds.length }}</span>
      </button>
    </div>

    <LoadingSkeleton v-if="loading" :rows="3" />

    <template v-else-if="tab === 'requests'">
      <EmptyState v-if="requests.length === 0">{{ t("friends.noRequests") }}</EmptyState>
      <ul v-else class="space-y-2">
        <li v-for="r in requests" :key="r.id" class="card flex items-center gap-3 p-3">
          <RouterLink :to="{ name: 'profile-by-id', params: { id: r.from_user_id } }">
            <UserAvatar :name="directory.nameOf(r.from_user_id) || r.from_user_id" />
          </RouterLink>
          <span class="flex-1 truncate text-sm font-medium">{{ directory.label(r.from_user_id, 12) }}</span>
          <FriendButton
            :user-id="r.from_user_id"
            :request-id="r.id"
            state="pending_in"
            @click="onResolved(r.id)"
          />
        </li>
      </ul>
    </template>

    <template v-else-if="tab === 'sent'">
      <EmptyState v-if="sent.length === 0">{{ t("friends.noSent") }}</EmptyState>
      <ul v-else class="space-y-2">
        <li v-for="r in sent" :key="r.id" class="card flex items-center gap-3 p-3">
          <RouterLink :to="{ name: 'profile-by-id', params: { id: r.to_user_id } }">
            <UserAvatar :name="directory.nameOf(r.to_user_id) || r.to_user_id" />
          </RouterLink>
          <span class="flex-1 truncate text-sm font-medium">{{ directory.label(r.to_user_id, 12) }}</span>
          <span class="text-xs text-gray-400">{{ t("profile.requestSent") }}</span>
          <button
            class="btn-ghost text-sm"
            :disabled="cancelling === r.id"
            @click="cancelRequest(r.id)"
          >
            {{ t("friends.cancel") }}
          </button>
        </li>
      </ul>
    </template>

    <template v-else>
      <EmptyState v-if="friendIds.length === 0">{{ t("friends.none") }}</EmptyState>
      <ul v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <li
          v-for="id in friendIds"
          :key="id"
          class="card group flex flex-col items-center gap-2 p-4 transition hover:shadow-md"
        >
          <!-- Avatar → profile -->
          <RouterLink
            :to="{ name: 'profile-by-id', params: { id }, query: { rel: 'friends' } }"
            class="relative rounded-full ring-brand-300 transition hover:ring-2"
            :aria-label="t('nav.profile')"
            :title="t('nav.profile')"
          >
            <UserAvatar :name="directory.nameOf(id) || id" :size="56" />
            <span
              v-if="presence.isOnline(id)"
              class="absolute -end-0.5 -bottom-0.5 h-3.5 w-3.5 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
              :title="t('presence.online')"
            />
          </RouterLink>
          <span class="truncate text-sm font-medium">{{ directory.label(id, 10) }}</span>
          <!-- Anywhere else → open chat in-app -->
          <button
            type="button"
            class="btn-soft w-full justify-center text-xs"
            :disabled="opening === id"
            @click="openChat(id)"
          >
            <MessageCircle class="h-4 w-4" /> {{ t("profile.message") }}
          </button>
        </li>
      </ul>
    </template>
  </AppShell>
</template>
