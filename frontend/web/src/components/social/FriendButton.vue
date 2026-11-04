<script setup lang="ts">
import { Check, ChevronDown, Rss, Star, UserCheck, UserMinus, UserPlus, UserX } from "lucide-vue-next";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import ConfirmActionDialog from "@/components/social/ConfirmActionDialog.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useRelationshipPrefs } from "@/lib/useRelationshipPrefs";
import { type FriendState, graphService } from "@/services/graph";
import { useToastStore } from "@/stores/toasts";

// The profile/friend-card friendship control. "Request sent" opens a menu to
// cancel (POST /friends/requests/<id>/reject/ also cancels your own request);
// "Friends" opens Favorites, Unfollow/Follow (when `following` is passed) and
// Unfriend (confirmed).
const props = withDefaults(
  defineProps<{ userId: string; state: FriendState; requestId?: string; name?: string; menu?: boolean; following?: boolean }>(),
  { requestId: undefined, name: "", menu: true, following: undefined },
);
const emit = defineEmits<{ change: [state: FriendState, requestId?: string]; "follow-change": [on: boolean] }>();

const { t } = useI18n();
const toasts = useToastStore();
const prefs = useRelationshipPrefs();
const current = ref<FriendState>(props.state);
const reqId = ref<string | undefined>(props.requestId);
// Friend state may resolve asynchronously on the profile; keep in sync.
watch(
  () => props.state,
  (v) => (current.value = v),
);
watch(
  () => props.requestId,
  (v) => (reqId.value = v),
);
const busy = ref(false);
const open = ref(false);
const confirmUnfriend = ref(false);
useEscapeKey(open, () => (open.value = false));

async function run(fn: () => Promise<string | void | undefined>, next: FriendState) {
  if (busy.value) return;
  busy.value = true;
  open.value = false;
  const prev = current.value;
  current.value = next;
  try {
    const id = await fn();
    if (typeof id === "string") reqId.value = id;
    if (next === "none" || next === "friends") reqId.value = undefined;
    emit("change", next, reqId.value);
    return true;
  } catch (e) {
    current.value = prev;
    toasts.error(e);
    return false;
  } finally {
    busy.value = false;
  }
}

const send = () => run(() => graphService.sendFriendRequest(props.userId), "pending_out");
const accept = () => run(() => graphService.acceptFriendRequest(reqId.value ?? ""), "friends");
const decline = () => run(() => graphService.declineFriendRequest(reqId.value ?? ""), "none");

async function cancelRequest() {
  // Without the id the old row can't be cancelled: find it among my outgoing requests.
  if (!reqId.value) {
    const rows = await graphService.outgoingRequests().catch(() => []);
    reqId.value = rows.find((r) => r.to_user_id === props.userId)?.id;
  }
  if (!reqId.value) return;
  if (await run(() => graphService.declineFriendRequest(reqId.value ?? ""), "none")) {
    toasts.success(t("people.actions.requestCancelled"));
  }
}

async function unfriend() {
  if (await run(() => graphService.removeFriend(props.userId), "none")) {
    confirmUnfriend.value = false;
    toasts.success(t("people.actions.unfriended"));
  }
}

async function toggleMenu() {
  open.value = !open.value;
  if (open.value && current.value === "friends") void prefs.ensure(["favorites"]);
}

async function toggleFavorite() {
  open.value = false;
  try {
    const on = await prefs.toggle("favorites", props.userId);
    toasts.success(t(on ? "people.actions.favoriteAdded" : "people.actions.favoriteRemoved"));
  } catch (e) {
    toasts.error(e, { favorites_limit: "people.actions.favoritesLimit" });
  }
}

// Friends follow each other by default; unfollowing keeps the friendship but drops their posts from the feed.
const followBusy = ref(false);
async function toggleFollow() {
  if (followBusy.value || props.following === undefined) return;
  open.value = false;
  followBusy.value = true;
  const on = !props.following;
  try {
    await (on ? graphService.follow(props.userId) : graphService.unfollow(props.userId));
    emit("follow-change", on);
    toasts.success(t(on ? "people.actions.followed" : "people.actions.unfollowed", { name: props.name || t("profile.unknownUser") }));
  } catch (e) {
    toasts.error(e);
  } finally {
    followBusy.value = false;
  }
}

const item =
  "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 disabled:opacity-60 dark:hover:bg-gray-800";
</script>

<template>
  <div class="relative inline-flex" data-testid="friend-button" :data-state="current">
    <button v-if="current === 'none'" class="btn-primary" :disabled="busy" @click="send">
      <UserPlus class="h-4 w-4" /> {{ t("profile.addFriend") }}
    </button>

    <template v-else-if="current === 'pending_in'">
      <div class="flex gap-2">
        <button class="btn-primary" :disabled="busy" @click="accept">
          <Check class="h-4 w-4" /> {{ t("profile.accept") }}
        </button>
        <button class="btn-ghost" :disabled="busy" @click="decline">
          <UserX class="h-4 w-4" /> {{ t("friends.delete") }}
        </button>
      </div>
    </template>

    <template v-else-if="!menu">
      <button v-if="current === 'pending_out'" class="btn-ghost" :disabled="busy" @click="cancelRequest">
        <UserX class="h-4 w-4" /> {{ t("people.actions.cancelRequest") }}
      </button>
      <button v-else class="btn-ghost" :disabled="busy" @click="confirmUnfriend = true">
        <UserMinus class="h-4 w-4" /> {{ t("people.actions.unfriend") }}
      </button>
    </template>

    <template v-else>
      <button
        class="btn-soft"
        :disabled="busy"
        aria-haspopup="menu"
        :aria-expanded="open"
        :aria-label="current === 'pending_out' ? t('profile.requestSent') : t('people.actions.friendsMenu')"
        @click="toggleMenu"
      >
        <component :is="current === 'pending_out' ? UserX : UserCheck" class="h-4 w-4" />
        {{ current === "pending_out" ? t("profile.requestSent") : t("profile.friendsLabel") }}
        <ChevronDown class="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      <template v-if="open">
        <div class="fixed inset-0 z-40" @click="open = false" />
        <div class="popover absolute end-0 top-full z-50 mt-2 w-60 p-1.5" role="menu">
          <button v-if="current === 'pending_out'" role="menuitem" :class="item" :disabled="busy" @click="cancelRequest">
            <UserX class="h-4 w-4" /> {{ t("people.actions.cancelRequest") }}
          </button>
          <template v-else>
            <button v-if="prefs.loaded('favorites')" role="menuitem" :class="item" :disabled="prefs.isBusy('favorites', userId)" @click="toggleFavorite">
              <Star class="h-4 w-4" :class="prefs.has('favorites', userId) ? 'fill-current text-amber-500' : ''" />
              {{ prefs.has("favorites", userId) ? t("people.actions.removeFavorite") : t("people.actions.addFavorite") }}
            </button>
            <button
              v-if="following !== undefined"
              role="menuitem"
              :class="item"
              :disabled="followBusy"
              data-testid="friend-menu-follow"
              @click="toggleFollow"
            >
              <component :is="following ? UserMinus : Rss" class="h-4 w-4" />
              <span dir="auto">{{ following ? t("people.actions.unfollow") : t("people.actions.follow") }}</span>
            </button>
            <button role="menuitem" :class="item" class="text-red-600 dark:text-red-400" @click="open = false; confirmUnfriend = true">
              <UserMinus class="h-4 w-4" /> {{ t("people.actions.unfriend") }}
            </button>
          </template>
        </div>
      </template>
    </template>

    <ConfirmActionDialog
      v-if="confirmUnfriend"
      :title="t('people.actions.unfriendTitle', { name: name || t('profile.unknownUser') })"
      :hint="t('people.actions.unfriendHint')"
      :confirm-label="t('people.actions.unfriend')"
      :busy="busy"
      @confirm="unfriend"
      @cancel="confirmUnfriend = false"
    />
  </div>
</template>
