<script setup lang="ts">
// A hover card on a person's or a Page's name: picture, name, a line about
// them (intro or category, mutual friends), followers, and the real actions
// (Message, Follow, Add friend / Confirm for people; Follow and Message for
// Pages). It opens after a short pause under a mouse, or when the name gets
// keyboard focus; it never opens on touch. The data loads only when it first
// opens (lib/hoverCard). Escape closes it; the pointer can move onto it.
import { Check, Clock, MessageCircle, UserPlus, Users } from "lucide-vue-next";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import {
  canHover,
  type CardData,
  cardData,
  friendState as stateOf,
  type FriendState,
  myRelations,
  useCardsOf,
} from "@/lib/hoverCard";
import { pageCategoryLabel } from "@/lib/pageCategory";
import { useMediaUrl } from "@/lib/useMediaUrl";
import { chatService } from "@/services/chat";
import { graphService } from "@/services/graph";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";

const props = withDefaults(defineProps<{ kind?: "user" | "page"; id: string; tag?: string }>(), {
  kind: "user",
  tag: "span",
});

const i18n = useI18n();
const { t } = i18n;
const router = useRouter();
const auth = useAuthStore();
const toasts = useToastStore();

const OPEN_DELAY = 450;
const CLOSE_DELAY = 200;

const open = ref(false);
const loading = ref(false);
const data = ref<CardData | null>(null);
const unavailable = ref(false);
const fstate = ref<FriendState>("none");
const requestId = ref<string | null>(null);
const following = ref<boolean | null>(null);
const busy = ref(false);
const root = ref<HTMLElement | null>(null);
const uid = `hc-${Math.random().toString(36).slice(2, 9)}`;

const isSelf = computed(() => props.kind === "user" && auth.account?.id === props.id);
const enabled = computed(() => !!props.id && !!auth.account && !isSelf.value);

let openTimer: number | null = null;
let closeTimer: number | null = null;
function clearTimers() {
  if (openTimer) window.clearTimeout(openTimer);
  if (closeTimer) window.clearTimeout(closeTimer);
  openTimer = closeTimer = null;
}
// Escape closes an open card wherever focus is (a mouse-opened card has none inside it).
function onWindowKey(e: KeyboardEvent) {
  if (e.key === "Escape" && open.value) {
    clearTimers();
    open.value = false;
  }
}
watch(open, (now) => {
  if (now) window.addEventListener("keydown", onWindowKey);
  else window.removeEventListener("keydown", onWindowKey);
});
onBeforeUnmount(() => {
  clearTimers();
  window.removeEventListener("keydown", onWindowKey);
});

async function load() {
  if (data.value || loading.value) return;
  useCardsOf(auth.account?.id ?? "");
  loading.value = true;
  unavailable.value = false;
  try {
    const card = await cardData(props.kind, props.id);
    if (!card) {
      unavailable.value = true;
      return;
    }
    data.value = card;
    if (card.kind === "page") {
      following.value = card.following;
    } else {
      try {
        const rel = await myRelations();
        fstate.value = stateOf(rel, props.id);
        requestId.value = rel.incoming.get(props.id) ?? null;
        following.value = rel.following.has(props.id);
      } catch {
        // Unknown relationship: offer no relationship action rather than a wrong one.
        following.value = null;
        fstate.value = "friends";
      }
    }
  } finally {
    loading.value = false;
  }
}

function show(delay = OPEN_DELAY) {
  if (!enabled.value) return;
  if (closeTimer) window.clearTimeout(closeTimer);
  closeTimer = null;
  if (open.value || openTimer) return;
  openTimer = window.setTimeout(() => {
    openTimer = null;
    open.value = true;
    void load();
  }, delay);
}
function hide(delay = CLOSE_DELAY) {
  if (openTimer) window.clearTimeout(openTimer);
  openTimer = null;
  if (!open.value) return;
  if (closeTimer) window.clearTimeout(closeTimer);
  closeTimer = window.setTimeout(() => {
    closeTimer = null;
    open.value = false;
  }, delay);
}

function onPointerEnter(e: PointerEvent) {
  if (e.pointerType === "mouse" && canHover()) show();
}
function onPointerLeave(e: PointerEvent) {
  if (e.pointerType === "mouse") hide();
}
function onFocusIn(e: FocusEvent) {
  const target = e.target as HTMLElement | null;
  let keyboard = false;
  try {
    keyboard = !!target?.matches(":focus-visible");
  } catch {
    keyboard = false;
  }
  if (keyboard) show(OPEN_DELAY);
  else if (closeTimer) {
    window.clearTimeout(closeTimer);
    closeTimer = null;
  }
}
function onFocusOut(e: FocusEvent) {
  const next = e.relatedTarget as Node | null;
  if (next && root.value?.contains(next)) return;
  hide(0);
}
function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && (open.value || openTimer)) {
    e.stopPropagation();
    clearTimers();
    open.value = false;
  }
}

// ---- actions ---------------------------------------------------------------------------
async function run(fn: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  try {
    await fn();
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

const addFriend = () =>
  run(async () => {
    await graphService.sendFriendRequest(props.id);
    fstate.value = "pending_out";
    (await myRelations()).outgoing.add(props.id);
  });
const confirmFriend = () =>
  run(async () => {
    if (!requestId.value) return;
    await graphService.acceptFriendRequest(requestId.value);
    fstate.value = "friends";
    const rel = await myRelations();
    rel.incoming.delete(props.id);
    rel.friends.add(props.id);
  });
const toggleFollow = () =>
  run(async () => {
    const next = !following.value;
    if (props.kind === "page") {
      if (next) await graphService.followPage(props.id);
      else await graphService.unfollowPage(props.id);
    } else {
      if (next) await graphService.follow(props.id);
      else await graphService.unfollow(props.id);
      const rel = await myRelations();
      if (next) rel.following.add(props.id);
      else rel.following.delete(props.id);
    }
    following.value = next;
    const d = data.value;
    if (d && d.followers !== null) d.followers = Math.max(0, d.followers + (next ? 1 : -1));
    if (d && d.kind === "page") d.following = next;
  });
const message = () =>
  run(async () => {
    const convo = props.kind === "page" ? await chatService.openPage(props.id) : await chatService.openDm(props.id);
    open.value = false;
    await router.push({ name: "messages", params: { id: convo.id } });
  });

// ---- display ---------------------------------------------------------------------------
const cover = useMediaUrl(() => data.value?.cover ?? null);
const to = computed(() =>
  props.kind === "page" ? { name: "page-by-id", params: { id: props.id } } : { name: "profile-by-id", params: { id: props.id } },
);
const fmt = (n: number) => new Intl.NumberFormat(i18n.locale.value).format(n);
const subline = computed(() => {
  const d = data.value;
  if (!d) return "";
  if (d.kind === "page") return pageCategoryLabel(d.category, i18n);
  return d.intro || (d.city ? t("polish.hover.livesIn", { place: d.city }) : "");
});
const pageTeam = computed(() => data.value?.kind === "page" && !!data.value.myRole);
const canMessagePage = computed(() => data.value?.kind === "page" && !data.value.myRole && data.value.status === "published");
</script>

<template>
  <component
    :is="tag"
    ref="root"
    class="relative"
    @pointerenter="onPointerEnter"
    @pointerleave="onPointerLeave"
    @focusin="onFocusIn"
    @focusout="onFocusOut"
    @keydown="onKeydown"
  >
    <slot />
    <div
      v-if="open"
      :id="uid"
      role="dialog"
      :aria-label="data ? data.name : t('polish.hover.label')"
      class="absolute start-0 top-full z-50 mt-1 w-80 max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl bg-white text-start font-normal text-gray-900 shadow-pop ring-1 ring-gray-200 dark:bg-gray-900 dark:text-gray-100 dark:ring-gray-700"
      data-testid="hover-card"
      :data-kind="kind"
    >
      <div v-if="loading && !data" class="flex items-center gap-3 p-4" aria-busy="true">
        <span class="h-14 w-14 animate-pulse rounded-full bg-gray-200 dark:bg-gray-700" />
        <span class="flex-1 space-y-2">
          <span class="block h-3 w-2/3 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
          <span class="block h-3 w-1/2 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
        </span>
      </div>
      <p v-else-if="unavailable" class="p-4 text-sm text-gray-600 dark:text-gray-300" data-testid="hover-card-unavailable">
        {{ t("polish.hover.unavailable") }}
      </p>
      <template v-else-if="data">
        <div class="h-16 bg-gradient-to-br from-brand-600 to-accent-500" :style="cover ? { backgroundImage: `url(${cover})`, backgroundSize: 'cover', backgroundPosition: 'center' } : undefined" aria-hidden="true" />
        <div class="-mt-8 flex items-end gap-3 px-4">
          <RouterLink :to="to" tabindex="-1" aria-hidden="true" class="shrink-0 rounded-full ring-4 ring-white dark:ring-gray-900">
            <UserAvatar :name="data.name" :media-id="data.avatar" :size="64" />
          </RouterLink>
        </div>
        <div class="px-4 pb-4 pt-2">
          <RouterLink :to="to" class="block truncate text-start text-lg font-bold hover:underline" data-testid="hover-card-name">
            <bdi>{{ data.name }}</bdi>
          </RouterLink>
          <p v-if="data.handle" class="truncate text-start text-xs text-gray-600 dark:text-gray-400"><bdi dir="ltr">@{{ data.handle }}</bdi></p>
          <p v-if="subline" class="mt-1 line-clamp-2 text-start text-sm text-gray-700 dark:text-gray-300" data-testid="hover-card-subline"><bdi>{{ subline }}</bdi></p>
          <ul class="mt-2 space-y-1 text-sm text-gray-700 dark:text-gray-300">
            <li v-if="data.followers !== null" class="flex items-center gap-2" data-testid="hover-card-followers">
              <Users class="h-4 w-4 shrink-0 text-gray-500 dark:text-gray-400" aria-hidden="true" />
              {{ t("polish.hover.followers", { count: fmt(data.followers) }, data.followers) }}
            </li>
            <li v-if="data.kind === 'user' && data.mutual" class="flex items-center gap-2" data-testid="hover-card-mutual">
              <Users class="h-4 w-4 shrink-0 text-gray-500 dark:text-gray-400" aria-hidden="true" />
              {{ t("polish.hover.mutual", { count: fmt(data.mutual) }, data.mutual) }}
            </li>
          </ul>

          <div class="mt-3 flex flex-wrap gap-2">
            <template v-if="data.kind === 'user'">
              <button v-if="fstate === 'none'" type="button" class="btn-primary flex-1 px-3 py-1.5" :disabled="busy" data-testid="hover-card-add" @click="addFriend">
                <UserPlus class="h-4 w-4" aria-hidden="true" /> {{ t("polish.hover.addFriend") }}
              </button>
              <button v-else-if="fstate === 'pending_in'" type="button" class="btn-primary flex-1 px-3 py-1.5" :disabled="busy || !requestId" data-testid="hover-card-confirm" @click="confirmFriend">
                <Check class="h-4 w-4" aria-hidden="true" /> {{ t("polish.hover.confirm") }}
              </button>
              <span v-else-if="fstate === 'pending_out'" class="btn flex-1 cursor-default bg-gray-100 px-3 py-1.5 text-gray-800 dark:bg-gray-800 dark:text-gray-100" role="status" data-testid="hover-card-requested">
                <Clock class="h-4 w-4" aria-hidden="true" /> {{ t("polish.hover.requested") }}
              </span>
              <button type="button" class="btn flex-1 bg-gray-100 px-3 py-1.5 text-gray-900 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700" :disabled="busy" data-testid="hover-card-message" @click="message">
                <MessageCircle class="h-4 w-4" aria-hidden="true" /> {{ t("polish.hover.message") }}
              </button>
              <button
                v-if="following !== null"
                type="button"
                class="btn-outline px-3 py-1.5"
                :aria-pressed="following"
                :disabled="busy"
                data-testid="hover-card-follow"
                @click="toggleFollow"
              >
                {{ following ? t("polish.hover.following") : t("polish.hover.follow") }}
              </button>
            </template>
            <template v-else>
              <button
                v-if="following !== null && !pageTeam"
                type="button"
                class="btn-primary flex-1 px-3 py-1.5"
                :aria-pressed="!!following"
                :disabled="busy"
                data-testid="hover-card-follow"
                @click="toggleFollow"
              >
                {{ following ? t("polish.hover.following") : t("polish.hover.follow") }}
              </button>
              <button v-if="canMessagePage" type="button" class="btn flex-1 bg-gray-100 px-3 py-1.5 text-gray-900 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700" :disabled="busy" data-testid="hover-card-message" @click="message">
                <MessageCircle class="h-4 w-4" aria-hidden="true" /> {{ t("polish.hover.message") }}
              </button>
              <RouterLink v-if="pageTeam" :to="to" class="btn-soft flex-1 px-3 py-1.5">{{ t("polish.hover.viewPage") }}</RouterLink>
            </template>
          </div>
        </div>
      </template>
    </div>
  </component>
</template>
