<script setup lang="ts">
import { Check, MessageCircle, X } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import SponsoredCard from "@/components/post/SponsoredCard.vue";
import TrendingList from "@/components/search/TrendingList.vue";
import { dateBadge, formatRange } from "@/lib/eventTime";
import { relativeTime } from "@/lib/format";
import { chatService } from "@/services/chat";
import { useChatDockStore } from "@/stores/chatDock";
import type { TaraEvent } from "@/services/events";
import { type FriendRequest, graphService } from "@/services/graph";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";
import { useToastStore } from "@/stores/toasts";

import RailBirthdays from "./RailBirthdays.vue";
import RailPageSuggestions from "./RailPageSuggestions.vue";
import RailPeopleSuggestions from "./RailPeopleSuggestions.vue";
import { railAd, railHeading, railSection, railVisible, upcomingEvents } from "./rightRail";

const MAX_REQUESTS = 3;
const MAX_CONTACTS = 20;

const { t, locale } = useI18n();
const router = useRouter();
const chatDock = useChatDockStore();
const route = useRoute();
// The home feed's slot, on Home only, and only while this column is on screen.
const ad = computed(() => (railVisible.value && route.name === "home" ? railAd.value : null));
const presence = usePresenceStore();
const directory = useDirectoryStore();
const toasts = useToastStore();
const requests = ref<FriendRequest[]>([]);
const friendIds = ref<string[]>([]);
const events = ref<TaraEvent[]>([]);
const opening = ref("");
const resolving = ref("");

// Online friends first; otherwise the graph's order.
const contacts = computed(() =>
  [...friendIds.value]
    .slice(0, MAX_CONTACTS * 3)
    .sort((a, b) => Number(presence.isOnline(b)) - Number(presence.isOnline(a)))
    .slice(0, MAX_CONTACTS),
);

async function load() {
  const [reqs, friends, upcoming] = await Promise.all([
    graphService.incomingRequests().catch(() => []),
    graphService.friends().catch(() => []),
    upcomingEvents().catch(() => []),
  ]);
  requests.value = reqs;
  friendIds.value = friends;
  events.value = upcoming;
}

async function resolve(request: FriendRequest, accept: boolean) {
  if (resolving.value) return;
  resolving.value = request.id;
  try {
    if (accept) await graphService.acceptFriendRequest(request.id);
    else await graphService.declineFriendRequest(request.id);
    requests.value = requests.value.filter((r) => r.id !== request.id);
    if (accept && !friendIds.value.includes(request.from_user_id)) {
      friendIds.value = [request.from_user_id, ...friendIds.value];
    }
  } catch (e) {
    toasts.error(e);
  } finally {
    resolving.value = "";
  }
}

async function openChat(friendId: string) {
  if (opening.value) return;
  opening.value = friendId;
  try {
    const convo = await chatService.openDm(friendId);
    // Desktop: a docked mini chat keeps the page open (ChatDock); phones open the inbox.
    if (chatDock.available()) chatDock.open(convo.id);
    else router.push(`/messages/${convo.id}`);
  } catch (e) {
    toasts.error(e);
  } finally {
    opening.value = "";
  }
}

const badge = (iso: string) => dateBadge(iso, locale.value);

onMounted(load);

const heading = railHeading;
const section = railSection;
</script>

<template>
  <!-- pb-28: room for the chat dock's New message button (bottom end, lg+) -->
  <div class="space-y-3 pb-28" data-testid="right-rail">
    <!-- Sponsored: only when an ad was actually served (never an empty card) -->
    <section v-if="ad" :class="section" aria-labelledby="rs-sponsored" data-testid="rail-sponsored">
      <h2 id="rs-sponsored" :class="heading">{{ t("shell.rail.sponsored") }}</h2>
      <SponsoredCard :ad="ad" />
    </section>

    <!-- Trending hashtags (T4): hides itself when nothing is trending -->
    <TrendingList compact :limit="5" :class="section" />

    <!-- Friend requests -->
    <section v-if="requests.length" :class="section" aria-labelledby="rs-requests" data-testid="rail-requests">
      <h2 id="rs-requests" class="flex items-center justify-between" :class="heading">
        <span>{{ t("shell.rail.requests") }}</span>
        <RouterLink to="/friends" class="text-sm font-medium text-brand-600 hover:underline dark:text-brand-300">
          {{ t("shell.rail.seeAll") }}
        </RouterLink>
      </h2>
      <ul class="space-y-1">
        <li
          v-for="r in requests.slice(0, MAX_REQUESTS)"
          :key="r.id"
          class="flex gap-3 rounded-xl p-2 transition hover:bg-gray-200/60 dark:hover:bg-gray-800/60"
          data-testid="rail-request"
        >
          <RouterLink :to="{ name: 'profile-by-id', params: { id: r.from_user_id } }" class="shrink-0">
            <UserAvatar :name="directory.label(r.from_user_id)" :media-id="directory.avatarOf(r.from_user_id)" :size="52" />
          </RouterLink>
          <div class="min-w-0 flex-1">
            <div class="flex items-baseline justify-between gap-2">
              <RouterLink
                :to="{ name: 'profile-by-id', params: { id: r.from_user_id } }"
                class="truncate text-sm font-semibold hover:underline"
                dir="auto"
              >
                {{ directory.label(r.from_user_id) }}
              </RouterLink>
              <span class="shrink-0 text-xs text-gray-600 dark:text-gray-400">{{ relativeTime(r.created_at) }}</span>
            </div>
            <div class="mt-2 flex gap-2">
              <button
                type="button"
                class="btn-primary flex-1 px-3 py-1.5"
                :disabled="resolving === r.id"
                data-testid="rail-request-accept"
                @click="resolve(r, true)"
              >
                <Check class="h-4 w-4" aria-hidden="true" /> {{ t("profile.accept") }}
              </button>
              <button
                type="button"
                class="btn flex-1 bg-gray-200 px-3 py-1.5 text-gray-800 hover:bg-gray-300 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
                :disabled="resolving === r.id"
                data-testid="rail-request-delete"
                @click="resolve(r, false)"
              >
                <X class="h-4 w-4" aria-hidden="true" /> {{ t("friends.delete") }}
              </button>
            </div>
          </div>
        </li>
      </ul>
    </section>

    <!-- Friends' birthdays today; hides itself when there are none -->
    <RailBirthdays />

    <!-- People you may know, then suggested pages (wave 2D); each hides itself when empty -->
    <RailPeopleSuggestions />
    <RailPageSuggestions />

    <!-- Your upcoming events -->
    <section v-if="events.length" :class="section" aria-labelledby="rs-events" data-testid="rail-events">
      <h2 id="rs-events" class="flex items-center justify-between" :class="heading">
        <span>{{ t("shell.rail.events") }}</span>
        <RouterLink to="/events" class="text-sm font-medium text-brand-600 hover:underline dark:text-brand-300">
          {{ t("shell.rail.seeAll") }}
        </RouterLink>
      </h2>
      <ul class="space-y-1">
        <li v-for="e in events" :key="e.id">
          <RouterLink
            :to="`/events/${e.id}`"
            class="flex items-center gap-3 rounded-xl p-2 transition hover:bg-gray-200/60 dark:hover:bg-gray-800/60"
          >
            <span class="flex h-11 w-11 shrink-0 flex-col items-center justify-center rounded-xl bg-accent-100 text-accent-800 dark:bg-accent-900/40 dark:text-accent-200">
              <span class="text-[10px] font-bold uppercase leading-none">{{ badge(e.starts_at).month }}</span>
              <span class="text-base font-extrabold leading-tight">{{ badge(e.starts_at).day }}</span>
            </span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-semibold" dir="auto">{{ e.title }}</span>
              <span class="block truncate text-xs text-gray-600 dark:text-gray-400">
                {{ formatRange(e.starts_at, e.ends_at, locale) }}
              </span>
            </span>
          </RouterLink>
        </li>
      </ul>
    </section>

    <!-- Contacts: friends with live presence; a click opens the chat -->
    <section :class="section" aria-labelledby="rs-contacts" data-testid="rail-contacts">
      <h2 id="rs-contacts" class="flex items-center justify-between" :class="heading">
        <span>{{ t("shell.rail.contacts") }}</span>
        <RouterLink v-if="friendIds.length" to="/friends" class="text-sm font-medium text-brand-600 hover:underline dark:text-brand-300">
          {{ t("friends.all") }}
        </RouterLink>
      </h2>
      <p v-if="!friendIds.length" class="px-2 text-sm text-gray-600 dark:text-gray-400">{{ t("shell.rail.noContacts") }}</p>
      <ul v-else class="space-y-0.5">
        <li v-for="id in contacts" :key="id" class="group flex items-center gap-3 rounded-xl p-2 transition hover:bg-gray-200/60 dark:hover:bg-gray-800/60">
          <RouterLink
            :to="{ name: 'profile-by-id', params: { id } }"
            class="relative shrink-0 rounded-full ring-brand-300 transition hover:ring-2"
            :aria-label="`${t('nav.profile')}: ${directory.label(id)}`"
          >
            <UserAvatar :name="directory.label(id)" :media-id="directory.avatarOf(id)" :size="36" />
            <span
              v-if="presence.isOnline(id)"
              class="absolute -bottom-0.5 -end-0.5 h-3 w-3 rounded-full border-2 border-gray-100 bg-green-500 dark:border-gray-950"
              :title="t('presence.online')"
            />
          </RouterLink>
          <button
            type="button"
            class="flex min-w-0 flex-1 items-center gap-2 text-start text-sm font-semibold disabled:opacity-60"
            :disabled="opening === id"
            :aria-label="t('shell.rail.openChat', { name: directory.label(id) })"
            data-testid="rail-contact"
            @click="openChat(id)"
          >
            <span class="min-w-0 flex-1 truncate text-start"><bdi>{{ directory.label(id) }}</bdi></span>
            <MessageCircle class="h-4 w-4 shrink-0 text-gray-400 opacity-0 transition group-hover:opacity-100" aria-hidden="true" />
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>
