<script setup lang="ts">
import { Cake, Home, MessageCircle, Search, Send, UserCheck, UserPlus, Users, UsersRound } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import FriendRequestCard from "@/components/friends/FriendRequestCard.vue";
import FriendsBirthdays from "@/components/friends/FriendsBirthdays.vue";
import SuggestionCard from "@/components/friends/SuggestionCard.vue";
import AppShell from "@/components/layout/AppShell.vue";
import PersonActionsMenu from "@/components/social/PersonActionsMenu.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { chatService } from "@/services/chat";
import { type FriendRequest, graphService } from "@/services/graph";
import { type PersonSuggestion, relationshipsService } from "@/services/relationships";
import { useDirectoryStore } from "@/stores/directory";
import { usePresenceStore } from "@/stores/presence";
import { useToastStore } from "@/stores/toasts";

// Friends hub in the reference layout: a left section list (home, requests,
// suggestions, birthdays, all friends, sent requests) and a card grid. Home is
// the default: pending requests (when there are any) above People you may know.
// The section lives in ?tab= so menus, notifications and the rail's "See all"
// can deep-link to it.
const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const presence = usePresenceStore();
const directory = useDirectoryStore();
const toasts = useToastStore();

type Tab = "home" | "requests" | "suggestions" | "birthdays" | "all" | "sent";
const TABS: { id: Tab; icon: typeof Users; label: string }[] = [
  { id: "home", icon: Home, label: "socialShell.friends.home" },
  { id: "requests", icon: UserPlus, label: "people.friendsHub.home" },
  { id: "suggestions", icon: UsersRound, label: "people.friendsHub.suggestions" },
  { id: "birthdays", icon: Cake, label: "socialShell.friends.birthdays" },
  { id: "all", icon: Users, label: "people.friendsHub.all" },
  { id: "sent", icon: Send, label: "people.friendsHub.sent" },
];
/** Requests shown on Home before "See all". */
const HOME_REQUESTS = 8;
const fromQuery = (v: unknown): Tab => (TABS.some((x) => x.id === v) ? (v as Tab) : "home");
const tab = ref<Tab>(fromQuery(route.query.tab));
watch(
  () => route.query.tab,
  (v) => (tab.value = fromQuery(v)),
);
function select(next: Tab) {
  if (next === tab.value) return;
  tab.value = next;
  void router.replace({ query: { ...route.query, tab: next === "home" ? undefined : next } });
}

const requests = ref<FriendRequest[]>([]);
const sent = ref<FriendRequest[]>([]);
const friendIds = ref<string[]>([]);
const suggestions = ref<PersonSuggestion[] | null>(null);
const suggestionsFailed = ref(false);
const loading = ref(true);
const busy = ref("");
const opening = ref("");
// Per-suggestion outcome: a request we sent (its id, to cancel) or a dismissal (to undo).
const sentTo = ref<Record<string, string>>({});
const dismissed = ref<Record<string, true>>({});
const query = ref("");

async function load() {
  loading.value = true;
  try {
    const [incoming, outgoing, friends] = await Promise.all([
      graphService.incomingRequests().catch(() => [] as FriendRequest[]),
      graphService.outgoingRequests().catch(() => [] as FriendRequest[]),
      graphService.friends().catch(() => [] as string[]),
    ]);
    requests.value = incoming ?? [];
    sent.value = outgoing ?? [];
    friendIds.value = friends ?? [];
  } finally {
    loading.value = false;
  }
}

async function loadSuggestions() {
  suggestionsFailed.value = false;
  try {
    suggestions.value = await relationshipsService.people(30);
  } catch {
    suggestionsFailed.value = true;
  }
}

async function act(key: string, fn: () => Promise<void>) {
  if (busy.value) return;
  busy.value = key;
  try {
    await fn();
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = "";
  }
}

const confirmRequest = (r: FriendRequest) =>
  act(r.id, async () => {
    await graphService.acceptFriendRequest(r.id);
    requests.value = requests.value.filter((x) => x.id !== r.id);
    friendIds.value = [r.from_user_id, ...friendIds.value.filter((x) => x !== r.from_user_id)];
  });
const deleteRequest = (r: FriendRequest) =>
  act(r.id, async () => {
    await graphService.declineFriendRequest(r.id);
    requests.value = requests.value.filter((x) => x.id !== r.id);
  });
const cancelSent = (r: FriendRequest) =>
  act(r.id, async () => {
    await graphService.declineFriendRequest(r.id);
    sent.value = sent.value.filter((x) => x.id !== r.id);
    toasts.success(t("people.actions.requestCancelled"));
  });

const addSuggested = (id: string) =>
  act(id, async () => {
    const requestId = await graphService.sendFriendRequest(id);
    sentTo.value = { ...sentTo.value, [id]: requestId ?? "" };
    if (requestId) sent.value = [{ id: requestId, from_user_id: "", to_user_id: id, created_at: new Date().toISOString() }, ...sent.value];
  });
const cancelSuggested = (id: string) =>
  act(id, async () => {
    let requestId = sentTo.value[id];
    if (!requestId) requestId = (await graphService.outgoingRequests()).find((r) => r.to_user_id === id)?.id ?? "";
    if (!requestId) return;
    await graphService.declineFriendRequest(requestId);
    const next = { ...sentTo.value };
    delete next[id];
    sentTo.value = next;
    sent.value = sent.value.filter((r) => r.id !== requestId);
  });
const dismissSuggested = (id: string) =>
  act(id, async () => {
    await relationshipsService.dismiss(id, "user");
    dismissed.value = { ...dismissed.value, [id]: true };
  });
const undoDismiss = (id: string) =>
  act(id, async () => {
    await relationshipsService.undismiss(id, "user");
    const next = { ...dismissed.value };
    delete next[id];
    dismissed.value = next;
  });

async function openChat(friendId: string) {
  if (opening.value) return;
  opening.value = friendId;
  try {
    const convo = await chatService.openDm(friendId);
    router.push(`/messages/${convo.id}`);
  } catch (e) {
    toasts.error(e);
  } finally {
    opening.value = "";
  }
}

function dropFriend(id: string) {
  friendIds.value = friendIds.value.filter((x) => x !== id);
}

function suggestionState(id: string): "idle" | "sent" | "dismissed" {
  if (dismissed.value[id]) return "dismissed";
  return id in sentTo.value ? "sent" : "idle";
}

const shownFriends = computed(() => {
  const q = query.value.trim().toLowerCase();
  return q ? friendIds.value.filter((id) => directory.label(id).toLowerCase().includes(q)) : friendIds.value;
});

function count(tb: Tab): number | null {
  if (tb === "requests") return requests.value.length || null;
  if (tb === "sent") return sent.value.length || null;
  if (tb === "all") return friendIds.value.length || null;
  return null;
}

watch(
  tab,
  (tb) => {
    if ((tb === "suggestions" || tb === "home") && suggestions.value === null) void loadSuggestions();
  },
  { immediate: true },
);
onMounted(load);

const grid = "grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4";
const seeAllBtn =
  "rounded-lg px-2 py-1 text-sm font-semibold text-brand-700 hover:bg-brand-50 dark:text-brand-300 dark:hover:bg-brand-900/40";
</script>

<template>
  <AppShell :left="false" :right="false">
    <div class="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[360px_minmax(0,1fr)]">
      <!-- Section list -->
      <aside class="card h-fit p-2 lg:sticky lg:top-20">
        <h1 class="px-2 pb-2 pt-1 text-2xl font-extrabold">{{ t("people.friendsHub.title") }}</h1>
        <nav :aria-label="t('people.friendsHub.nav')" class="flex gap-1 overflow-x-auto lg:flex-col">
          <button
            v-for="x in TABS"
            :key="x.id"
            type="button"
            class="flex shrink-0 items-center gap-3 rounded-xl px-3 py-2 text-start text-[15px] font-semibold transition"
            :class="tab === x.id ? 'bg-brand-50 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200' : 'hover:bg-gray-100 dark:hover:bg-gray-800'"
            :aria-current="tab === x.id ? 'page' : undefined"
            :data-testid="`friends-tab-${x.id}`"
            @click="select(x.id)"
          >
            <span
              class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
              :class="tab === x.id ? 'bg-brand-600 text-white' : 'bg-gray-200 text-gray-800 dark:bg-gray-800 dark:text-gray-100'"
            >
              <component :is="x.icon" class="h-5 w-5" aria-hidden="true" />
            </span>
            <span class="flex-1 whitespace-nowrap">{{ t(x.label) }}</span>
            <span v-if="count(x.id)" class="rounded-full px-2 text-xs" :class="x.id === 'requests' ? 'bg-red-500 text-white' : 'text-gray-500 dark:text-gray-400'">
              {{ count(x.id) }}
            </span>
          </button>
        </nav>
      </aside>

      <section class="min-w-0" :aria-labelledby="`fh-${tab}`">
        <h2 :id="`fh-${tab}`" class="mb-3 text-xl font-bold" :class="tab === 'home' ? 'sr-only' : ''">{{ t(TABS.find((x) => x.id === tab)!.label) }}</h2>

        <!-- Birthdays: identity's list, loaded by the component itself -->
        <FriendsBirthdays v-if="tab === 'birthdays'" />

        <LoadingSkeleton v-else-if="loading && tab !== 'suggestions'" :rows="3" />

        <!-- Home: pending requests (if any), then People you may know -->
        <template v-else-if="tab === 'home'">
          <section v-if="requests.length" class="mb-6" aria-labelledby="fh-home-requests" data-testid="friends-home-requests">
            <div class="mb-2 flex items-center justify-between gap-2">
              <h3 id="fh-home-requests" class="text-xl font-bold">
                {{ t("socialShell.friends.requestsTitle") }}
                <span class="ms-1 text-base font-semibold text-red-600 dark:text-red-400">{{ requests.length }}</span>
              </h3>
              <button type="button" :class="seeAllBtn" data-testid="friends-home-requests-all" @click="select('requests')">
                {{ t("socialShell.friends.seeAll") }}
              </button>
            </div>
            <ul :class="grid">
              <FriendRequestCard
                v-for="r in requests.slice(0, HOME_REQUESTS)"
                :key="r.id"
                :account-id="r.from_user_id"
                :busy="busy === r.id"
                @confirm="confirmRequest(r)"
                @delete="deleteRequest(r)"
              />
            </ul>
          </section>
          <section aria-labelledby="fh-home-pymk" data-testid="friends-home-pymk">
            <div class="mb-2 flex items-center justify-between gap-2">
              <h3 id="fh-home-pymk" class="text-xl font-bold">{{ t("socialShell.friends.pymkTitle") }}</h3>
              <button v-if="suggestions?.length" type="button" :class="seeAllBtn" @click="select('suggestions')">
                {{ t("socialShell.friends.seeAll") }}
              </button>
            </div>
            <ErrorState v-if="suggestionsFailed" @retry="loadSuggestions" />
            <LoadingSkeleton v-else-if="suggestions === null" :rows="3" />
            <EmptyState v-else-if="suggestions.length === 0" class="card">{{ t("people.friendsHub.noSuggestions") }}</EmptyState>
            <ul v-else :class="grid">
              <SuggestionCard
                v-for="p in suggestions"
                :key="p.account_id"
                :person="p"
                :state="suggestionState(p.account_id)"
                :busy="busy === p.account_id"
                @add="addSuggested(p.account_id)"
                @cancel="cancelSuggested(p.account_id)"
                @remove="dismissSuggested(p.account_id)"
                @undo="undoDismiss(p.account_id)"
              />
            </ul>
          </section>
        </template>

        <!-- Friend requests -->
        <template v-else-if="tab === 'requests'">
          <EmptyState v-if="requests.length === 0" class="card">{{ t("friends.noRequests") }}</EmptyState>
          <ul v-else :class="grid">
            <FriendRequestCard
              v-for="r in requests"
              :key="r.id"
              :account-id="r.from_user_id"
              :busy="busy === r.id"
              @confirm="confirmRequest(r)"
              @delete="deleteRequest(r)"
            />
          </ul>
        </template>

        <!-- Suggestions -->
        <template v-else-if="tab === 'suggestions'">
          <ErrorState v-if="suggestionsFailed" @retry="loadSuggestions" />
          <LoadingSkeleton v-else-if="suggestions === null" :rows="3" />
          <EmptyState v-else-if="suggestions.length === 0" class="card">{{ t("people.friendsHub.noSuggestions") }}</EmptyState>
          <ul v-else :class="grid">
            <SuggestionCard
              v-for="p in suggestions"
              :key="p.account_id"
              :person="p"
              :state="suggestionState(p.account_id)"
              :busy="busy === p.account_id"
              @add="addSuggested(p.account_id)"
              @cancel="cancelSuggested(p.account_id)"
              @remove="dismissSuggested(p.account_id)"
              @undo="undoDismiss(p.account_id)"
            />
          </ul>
        </template>

        <!-- All friends -->
        <template v-else-if="tab === 'all'">
          <EmptyState v-if="friendIds.length === 0" class="card">{{ t("friends.none") }}</EmptyState>
          <template v-else>
            <label class="relative mb-3 block max-w-sm">
              <span class="sr-only">{{ t("people.friendsHub.searchFriends") }}</span>
              <Search class="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" aria-hidden="true" />
              <input v-model="query" type="search" class="input w-full ps-9" :placeholder="t('people.friendsHub.searchFriends')" />
            </label>
            <EmptyState v-if="shownFriends.length === 0" class="card">{{ t("people.friendsHub.noMatches") }}</EmptyState>
            <ul v-else class="grid gap-3 sm:grid-cols-2">
              <li v-for="id in shownFriends" :key="id" class="card flex items-center gap-3 p-3" data-testid="friend-card" :data-account-id="id">
                <RouterLink :to="{ name: 'profile-by-id', params: { id } }" class="relative shrink-0" tabindex="-1" aria-hidden="true">
                  <UserAvatar :name="directory.label(id)" :media-id="directory.avatarOf(id)" :size="64" />
                  <span
                    v-if="presence.isOnline(id)"
                    class="absolute -bottom-0.5 -end-0.5 h-3.5 w-3.5 rounded-full border-2 border-white bg-green-500 dark:border-gray-900"
                    :title="t('presence.online')"
                  />
                </RouterLink>
                <RouterLink :to="{ name: 'profile-by-id', params: { id } }" class="min-w-0 flex-1 truncate font-semibold hover:underline" dir="auto">
                  {{ directory.label(id) }}
                </RouterLink>
                <button
                  type="button"
                  class="btn-soft px-3 py-1.5"
                  :disabled="opening === id"
                  :aria-label="`${t('profile.message')} ${directory.label(id)}`"
                  @click="openChat(id)"
                >
                  <MessageCircle class="h-4 w-4" aria-hidden="true" />
                  <span class="hidden sm:inline">{{ t("profile.message") }}</span>
                </button>
                <PersonActionsMenu :user-id="id" :name="directory.label(id)" is-friend @unfriended="dropFriend(id)" @blocked="(on) => on && dropFriend(id)" />
              </li>
            </ul>
          </template>
        </template>

        <!-- Sent requests -->
        <template v-else>
          <EmptyState v-if="sent.length === 0" class="card">{{ t("friends.noSent") }}</EmptyState>
          <ul v-else class="grid gap-3 sm:grid-cols-2">
            <li v-for="r in sent" :key="r.id" class="card flex items-center gap-3 p-3" data-testid="sent-request-card">
              <RouterLink :to="{ name: 'profile-by-id', params: { id: r.to_user_id } }" class="shrink-0" tabindex="-1" aria-hidden="true">
                <UserAvatar :name="directory.label(r.to_user_id)" :media-id="directory.avatarOf(r.to_user_id)" :size="56" />
              </RouterLink>
              <div class="min-w-0 flex-1">
                <RouterLink :to="{ name: 'profile-by-id', params: { id: r.to_user_id } }" class="block truncate font-semibold hover:underline" dir="auto">
                  {{ directory.label(r.to_user_id) }}
                </RouterLink>
                <p class="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
                  <UserCheck class="h-3.5 w-3.5" aria-hidden="true" /> {{ t("people.friendsHub.requestSent") }}
                </p>
              </div>
              <button type="button" class="btn-soft px-3 py-1.5" :disabled="busy === r.id" @click="cancelSent(r)">
                {{ t("people.friendsHub.cancelRequest") }}
              </button>
            </li>
          </ul>
        </template>
      </section>
    </div>
  </AppShell>
</template>
