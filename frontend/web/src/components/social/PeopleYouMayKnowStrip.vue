<script setup lang="ts">
import { Check, ChevronRight, UserPlus, X } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { graphService } from "@/services/graph";
import { type PersonSuggestion, relationshipsService } from "@/services/relationships";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

// "People you may know" as a horizontal card strip inside the home feed, for
// screens without the right column (which shows the same list). Graph's real
// friends-of-friends suggestions only; nothing renders when there are none.
const { t } = useI18n();
const directory = useDirectoryStore();
const toasts = useToastStore();
const people = ref<PersonSuggestion[]>([]);
const sent = ref<Record<string, true>>({});
const busy = ref("");
const lastRemoved = ref<{ person: PersonSuggestion; index: number } | null>(null);
const scroller = ref<HTMLElement | null>(null);

onMounted(async () => {
  people.value = await relationshipsService.people(12).catch(() => []);
});

async function addFriend(id: string) {
  if (busy.value) return;
  busy.value = id;
  try {
    await graphService.sendFriendRequest(id);
    sent.value = { ...sent.value, [id]: true };
  } catch (e) {
    if ((e as { response?: { status?: number } })?.response?.status === 409) sent.value = { ...sent.value, [id]: true };
    else toasts.error(e);
  } finally {
    busy.value = "";
  }
}

async function dismiss(id: string) {
  if (busy.value) return;
  busy.value = id;
  try {
    await relationshipsService.dismiss(id, "user");
    const index = people.value.findIndex((p) => p.account_id === id);
    if (index >= 0) lastRemoved.value = { person: people.value[index], index };
    people.value = people.value.filter((p) => p.account_id !== id);
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = "";
  }
}

async function undo() {
  const removed = lastRemoved.value;
  if (!removed || busy.value) return;
  busy.value = removed.person.account_id;
  try {
    await relationshipsService.undismiss(removed.person.account_id, "user");
    const next = [...people.value];
    next.splice(removed.index, 0, removed.person);
    people.value = next;
    lastRemoved.value = null;
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = "";
  }
}

function next() {
  const el = scroller.value;
  if (!el) return;
  const dir = getComputedStyle(el).direction === "rtl" ? -1 : 1;
  el.scrollBy({ left: dir * el.clientWidth * 0.8, behavior: "smooth" });
}
</script>

<template>
  <section v-if="people.length || lastRemoved" class="card p-4" aria-labelledby="pymk-strip-title" data-testid="pymk-strip">
    <div class="mb-3 flex items-center justify-between gap-2">
      <h2 id="pymk-strip-title" class="text-[17px] font-bold">{{ t("suggestions.people") }}</h2>
      <RouterLink to="/friends?tab=suggestions" class="text-sm font-semibold text-brand-600 hover:underline dark:text-brand-300" data-testid="pymk-strip-see-all">
        {{ t("people.friendsHub.seeAll") }}
      </RouterLink>
    </div>
    <p v-if="lastRemoved" class="mb-3 flex items-center justify-between gap-2 rounded-xl bg-gray-100 px-3 py-2 text-sm dark:bg-gray-800" role="status">
      <span>{{ t("people.friendsHub.removed") }}</span>
      <button type="button" class="font-semibold text-brand-600 hover:underline dark:text-brand-300" :disabled="!!busy" data-testid="pymk-strip-undo" @click="undo">
        {{ t("people.friendsHub.undo") }}
      </button>
    </p>
    <div class="relative">
      <ul ref="scroller" class="-mx-1 flex snap-x gap-2 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
        <li
          v-for="p in people"
          :key="p.account_id"
          class="relative flex w-40 shrink-0 snap-start flex-col overflow-hidden rounded-xl border border-gray-200 dark:border-gray-800"
          data-testid="pymk-card"
          :data-account-id="p.account_id"
        >
          <button
            v-if="!sent[p.account_id]"
            type="button"
            class="absolute end-1.5 top-1.5 z-10 rounded-full bg-gray-900/60 p-1 text-white transition hover:bg-gray-900/80"
            :disabled="busy === p.account_id"
            :aria-label="t('suggestions.removeLabel', { name: directory.label(p.account_id) })"
            data-testid="pymk-card-dismiss"
            @click="dismiss(p.account_id)"
          >
            <X class="h-4 w-4" aria-hidden="true" />
          </button>
          <RouterLink :to="{ name: 'profile-by-id', params: { id: p.account_id } }" class="block" tabindex="-1" aria-hidden="true">
            <UserAvatar :name="directory.label(p.account_id)" :media-id="directory.avatarOf(p.account_id)" :size="160" class="!h-40 !w-40 !rounded-none" />
          </RouterLink>
          <div class="flex flex-1 flex-col p-2">
            <RouterLink :to="{ name: 'profile-by-id', params: { id: p.account_id } }" class="block truncate text-sm font-semibold hover:underline" dir="auto">
              {{ directory.label(p.account_id) }}
            </RouterLink>
            <p class="mb-2 truncate text-xs text-gray-600 dark:text-gray-400">
              {{ p.reason === "follows_you" && !p.mutual_count ? t("suggestions.followsYou") : t("suggestions.mutual", p.mutual_count) }}
            </p>
            <button
              v-if="!sent[p.account_id]"
              type="button"
              class="btn-soft mt-auto w-full px-2 py-1.5 text-sm"
              :disabled="busy === p.account_id"
              data-testid="pymk-card-add"
              @click="addFriend(p.account_id)"
            >
              <UserPlus class="h-4 w-4" aria-hidden="true" /> {{ t("suggestions.addFriend") }}
            </button>
            <span v-else class="btn mt-auto w-full cursor-default bg-brand-50 px-2 py-1.5 text-sm text-brand-700 dark:bg-brand-900/40 dark:text-brand-200" role="status">
              <Check class="h-4 w-4" aria-hidden="true" /> {{ t("suggestions.requestSent") }}
            </span>
          </div>
        </li>
      </ul>
      <button
        v-if="people.length > 2"
        type="button"
        class="absolute end-0 top-16 hidden h-10 w-10 items-center justify-center rounded-full bg-white shadow-pop ring-1 ring-gray-200 transition hover:bg-gray-50 sm:inline-flex dark:bg-gray-800 dark:ring-gray-700"
        :aria-label="t('people.friendsHub.scrollNext')"
        @click="next"
      >
        <ChevronRight class="h-5 w-5 rtl:rotate-180" aria-hidden="true" />
      </button>
    </div>
  </section>
</template>
