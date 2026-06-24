<script setup lang="ts">
import { MessageCircle } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import FriendButton from "@/components/social/FriendButton.vue";
import { chatService } from "@/services/chat";
import { type FriendRequest, graphService } from "@/services/graph";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";

const { t } = useI18n();
const router = useRouter();
const presence = usePresenceStore();
const directory = useDirectoryStore();
const requests = ref<FriendRequest[]>([]);
const friendIds = ref<string[]>([]);
const opening = ref("");

async function load() {
  const [reqs, friends] = await Promise.all([
    graphService.incomingRequests().catch(() => []),
    graphService.friends().catch(() => []),
  ]);
  requests.value = reqs;
  friendIds.value = friends;
}

function onResolved(id: string) {
  requests.value = requests.value.filter((r) => r.id !== id);
  setTimeout(() => graphService.friends().then((f) => (friendIds.value = f)).catch(() => {}), 600);
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
  <div class="space-y-5 p-3">
    <!-- Friend requests (top) -->
    <section v-if="requests.length" aria-labelledby="rs-requests">
      <h3 id="rs-requests" class="mb-2 px-1 text-sm font-bold text-gray-500">
        {{ t("friends.requests") }} <span class="text-brand-600">({{ requests.length }})</span>
      </h3>
      <ul class="space-y-1">
        <li
          v-for="r in requests"
          :key="r.id"
          class="rounded-xl p-2 transition hover:bg-gray-100 dark:hover:bg-gray-800/60"
        >
          <div class="flex items-center gap-2">
            <UserAvatar :name="directory.nameOf(r.from_user_id) || r.from_user_id" :size="40" />
            <span class="min-w-0 flex-1 truncate text-sm font-medium">
              {{ directory.label(r.from_user_id, 10) }}
            </span>
          </div>
          <div class="mt-2">
            <FriendButton
              :user-id="r.from_user_id"
              :request-id="r.id"
              state="pending_in"
              @click="onResolved(r.id)"
            />
          </div>
        </li>
      </ul>
    </section>

    <!-- Friends (enlarged, primary content of the rail) -->
    <section aria-labelledby="rs-friends">
      <h3 id="rs-friends" class="mb-3 flex items-center justify-between px-1 text-base font-bold">
        <span>{{ t("friends.title") }} <span class="text-gray-400">({{ friendIds.length }})</span></span>
        <RouterLink v-if="friendIds.length" to="/friends" class="text-xs font-medium text-brand-600">
          {{ t("friends.all") }}
        </RouterLink>
      </h3>
      <p v-if="!friendIds.length" class="px-1 text-sm text-gray-400">{{ t("friends.none") }}</p>
      <ul v-else class="space-y-1">
        <li
          v-for="id in friendIds.slice(0, 15)"
          :key="id"
          class="group flex items-center gap-3 rounded-2xl p-2 transition hover:bg-gray-100 hover:shadow-sm dark:hover:bg-gray-800/60"
        >
          <!-- Avatar → profile -->
          <RouterLink
            :to="{ name: 'profile-by-id', params: { id }, query: { rel: 'friends' } }"
            class="relative shrink-0 rounded-full ring-brand-300 transition hover:ring-2"
            :aria-label="t('nav.profile')"
            :title="t('nav.profile')"
          >
            <UserAvatar :name="directory.nameOf(id) || id" :size="48" />
            <span
              v-if="presence.isOnline(id)"
              class="absolute -end-0.5 -bottom-0.5 h-3 w-3 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
              :title="t('presence.online')"
            />
          </RouterLink>
          <!-- Anywhere else → open chat in-app -->
          <button
            type="button"
            class="min-w-0 flex-1 truncate text-start text-[15px] font-medium disabled:opacity-60"
            :disabled="opening === id"
            :title="t('profile.message')"
            @click="openChat(id)"
          >
            {{ directory.label(id, 14) }}
          </button>
          <button
            type="button"
            class="rounded-full p-2 text-gray-400 opacity-0 transition hover:bg-brand-50 hover:text-brand-600 group-hover:opacity-100 disabled:opacity-50 dark:hover:bg-brand-950/40"
            :disabled="opening === id"
            :aria-label="t('profile.message')"
            :title="t('profile.message')"
            @click="openChat(id)"
          >
            <MessageCircle class="h-5 w-5" />
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>
