<script setup lang="ts">
import { Ban, BellOff, Bell, Flag, Link2, Lock, MessageCircle, MoreHorizontal, ShieldMinus, Star, UserMinus, UserX } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import ConfirmActionDialog from "@/components/social/ConfirmActionDialog.vue";
import ReportDialog from "@/components/social/ReportDialog.vue";
import { sendFeedback } from "@/lib/feedFeedback";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { type PrefKind, useRelationshipPrefs } from "@/lib/useRelationshipPrefs";
import { graphService } from "@/services/graph";
import { useToastStore } from "@/stores/toasts";

// The "..." menu for another person (profile header, friend cards): favorites,
// mute, restrict, unfriend, block and report — all real graph/moderation calls.
// An item whose list failed to load stays hidden rather than guessing.
const props = withDefaults(
  defineProps<{
    userId: string;
    name: string;
    isFriend?: boolean;
    copyLink?: boolean;
    message?: boolean;
    privacyLink?: boolean;
    self?: boolean;
    buttonClass?: string;
    /** On a profile (R4, 07 WP 7.5-B2): offer "Don't recommend this creator". */
    hideCreator?: boolean;
  }>(),
  { isFriend: false, copyLink: false, message: false, privacyLink: false, self: false, buttonClass: "btn-ghost px-2", hideCreator: false },
);
const emit = defineEmits<{ unfriended: []; blocked: [on: boolean]; message: [] }>();

const { t } = useI18n();
const toasts = useToastStore();
const prefs = useRelationshipPrefs();
const open = ref(false);
const confirm = ref<"unfriend" | "block" | null>(null);
const reporting = ref(false);
const busy = ref(false);
useEscapeKey(open, () => (open.value = false));

function toggle() {
  open.value = !open.value;
  if (open.value && !props.self) void prefs.ensure();
}

const MESSAGES: Record<Exclude<PrefKind, "blocks">, [string, string]> = {
  favorites: ["people.actions.favoriteAdded", "people.actions.favoriteRemoved"],
  mutes: ["people.actions.muted", "people.actions.unmuted"],
  restricted: ["people.actions.restricted", "people.actions.unrestricted"],
};

async function flip(kind: Exclude<PrefKind, "blocks">) {
  open.value = false;
  try {
    const on = await prefs.toggle(kind, props.userId);
    toasts.success(t(MESSAGES[kind][on ? 0 : 1]));
  } catch (e) {
    toasts.error(e, { favorites_limit: "people.actions.favoritesLimit" });
  }
}

async function copy() {
  open.value = false;
  try {
    await navigator.clipboard.writeText(window.location.href);
    toasts.success(t("profile.linkCopied"));
  } catch {
    toasts.push({ text: t("errors.copyFailed"), icon: "error" });
  }
}

function blockClicked() {
  open.value = false;
  if (prefs.has("blocks", props.userId)) void doBlock(false);
  else confirm.value = "block";
}

async function doBlock(on: boolean) {
  busy.value = true;
  try {
    await prefs.set("blocks", props.userId, on);
    toasts.success(t(on ? "people.actions.blocked" : "people.actions.unblocked"));
    confirm.value = null;
    emit("blocked", on);
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

async function unfriend() {
  busy.value = true;
  try {
    await graphService.removeFriend(props.userId);
    toasts.success(t("people.actions.unfriended"));
    confirm.value = null;
    emit("unfriended");
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

// "Don't recommend this creator" (item_type=profile): out of every recommended source
// and people suggestion; following stays. Undo from the toast or My Algorithm.
async function dontRecommend() {
  open.value = false;
  busy.value = true;
  try {
    await sendFeedback({
      action: "hide_creator",
      itemType: "profile",
      itemId: props.userId,
      surface: "profile",
      text: t("myAlgorithm.toast.hideCreator", { name: props.name }),
      undoLabel: t("myAlgorithm.toast.undo"),
      undoneText: t("myAlgorithm.toast.undone"),
    });
  } finally {
    busy.value = false;
  }
}

const item =
  "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 disabled:opacity-60 dark:hover:bg-gray-800";
</script>

<template>
  <div class="relative">
    <button
      type="button"
      :class="buttonClass"
      :aria-label="self ? t('profile.more') : t('people.actions.more', { name })"
      aria-haspopup="menu"
      :aria-expanded="open"
      data-testid="person-actions"
      @click="toggle"
    >
      <MoreHorizontal class="h-5 w-5" />
    </button>
    <template v-if="open">
      <div class="fixed inset-0 z-40" @click="open = false" />
      <div class="popover absolute end-0 top-full z-50 mt-2 w-72 p-1.5" role="menu" data-testid="person-actions-menu">
        <button v-if="message" role="menuitem" :class="item" @click="open = false; emit('message')">
          <MessageCircle class="h-4 w-4" /> {{ t("people.actions.message") }}
        </button>
        <button v-if="copyLink" role="menuitem" :class="item" @click="copy">
          <Link2 class="h-4 w-4" /> {{ t("people.actions.copyLink") }}
        </button>
        <RouterLink v-if="self && privacyLink" role="menuitem" :class="item" to="/settings/privacy" @click="open = false">
          <Lock class="h-4 w-4" /> {{ t("people.hero.privacy") }}
        </RouterLink>
        <template v-if="!self">
          <button v-if="prefs.loaded('favorites')" role="menuitem" :class="item" :disabled="prefs.isBusy('favorites', userId)" @click="flip('favorites')">
            <Star class="h-4 w-4" :class="prefs.has('favorites', userId) ? 'fill-current text-amber-500' : ''" />
            {{ prefs.has("favorites", userId) ? t("people.actions.removeFavorite") : t("people.actions.addFavorite") }}
          </button>
          <button v-if="prefs.loaded('mutes')" role="menuitem" :class="item" :disabled="prefs.isBusy('mutes', userId)" @click="flip('mutes')">
            <component :is="prefs.has('mutes', userId) ? Bell : BellOff" class="h-4 w-4" />
            {{ prefs.has("mutes", userId) ? t("people.actions.unmute", { name }) : t("people.actions.mute", { name }) }}
          </button>
          <button v-if="prefs.loaded('restricted')" role="menuitem" :class="item" :disabled="prefs.isBusy('restricted', userId)" @click="flip('restricted')">
            <ShieldMinus class="h-4 w-4" />
            {{ prefs.has("restricted", userId) ? t("people.actions.unrestrict") : t("people.actions.restrict") }}
          </button>
          <button v-if="isFriend" role="menuitem" :class="item" @click="open = false; confirm = 'unfriend'">
            <UserMinus class="h-4 w-4" /> {{ t("people.actions.unfriend") }}
          </button>
          <button v-if="hideCreator" role="menuitem" :class="item" :disabled="busy" data-testid="person-hide-creator" @click="dontRecommend">
            <UserX class="h-4 w-4" />
            <span class="min-w-0">
              <span class="block" dir="auto">{{ t("myAlgorithm.menu.hideCreator", { name }) }}</span>
              <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.menu.hideCreatorHint") }}</span>
            </span>
          </button>
          <div class="my-1 border-t border-gray-100 dark:border-gray-800" />
          <button v-if="prefs.loaded('blocks')" role="menuitem" :class="item" class="text-red-600 dark:text-red-400" @click="blockClicked">
            <Ban class="h-4 w-4" /> {{ prefs.has("blocks", userId) ? t("people.actions.unblock") : t("people.actions.block") }}
          </button>
          <button role="menuitem" :class="item" @click="open = false; reporting = true">
            <Flag class="h-4 w-4" /> {{ t("people.actions.report") }}
          </button>
        </template>
      </div>
    </template>

    <ConfirmActionDialog
      v-if="confirm === 'unfriend'"
      :title="t('people.actions.unfriendTitle', { name })"
      :hint="t('people.actions.unfriendHint')"
      :confirm-label="t('people.actions.unfriend')"
      :busy="busy"
      @confirm="unfriend"
      @cancel="confirm = null"
    />
    <ConfirmActionDialog
      v-if="confirm === 'block'"
      :title="t('people.actions.blockTitle', { name })"
      :hint="t('people.actions.blockHint')"
      :confirm-label="t('people.actions.block')"
      :busy="busy"
      @confirm="doBlock(true)"
      @cancel="confirm = null"
    />
    <ReportDialog v-if="reporting" target-type="user" :target-id="userId" :name="name" @close="reporting = false" />
  </div>
</template>
