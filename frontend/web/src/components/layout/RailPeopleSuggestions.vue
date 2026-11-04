<script setup lang="ts">
import { Check, UserPlus } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { graphService } from "@/services/graph";
import { type PersonSuggestion, relationshipsService } from "@/services/relationships";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

import { MAX_RAIL_PEOPLE, railHeading, railSection } from "./rightRail";

// "People you may know": friends of friends from graph, most mutual friends
// first. Hidden when graph has nothing to suggest (never a placeholder).
const { t } = useI18n();
const directory = useDirectoryStore();
const toasts = useToastStore();
const people = ref<PersonSuggestion[]>([]);
const sent = ref<Record<string, true>>({});
const busy = ref("");
// The last removed suggestion and where it was, so "Undo" can put it back.
const lastRemoved = ref<{ person: PersonSuggestion; index: number } | null>(null);

async function load() {
  people.value = await relationshipsService.people(MAX_RAIL_PEOPLE * 2).catch(() => []);
}

async function addFriend(id: string) {
  if (busy.value) return;
  busy.value = id;
  try {
    await graphService.sendFriendRequest(id);
    sent.value = { ...sent.value, [id]: true };
  } catch (e) {
    // Already pending (a request from elsewhere): the button's job is done.
    if ((e as { response?: { status?: number } })?.response?.status === 409) {
      sent.value = { ...sent.value, [id]: true };
    } else {
      toasts.error(e);
    }
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

onMounted(load);
</script>

<template>
  <section v-if="people.length || lastRemoved" :class="railSection" aria-labelledby="rs-people" data-testid="rail-people">
    <div class="flex items-center justify-between">
      <h2 id="rs-people" :class="railHeading">{{ t("suggestions.people") }}</h2>
      <RouterLink
        to="/friends?tab=suggestions"
        class="rounded-md px-2 pb-2 text-sm font-medium text-brand-600 hover:underline dark:text-brand-300"
        data-testid="rail-people-see-all"
      >
        {{ t("people.friendsHub.seeAll") }}
      </RouterLink>
    </div>
    <p v-if="lastRemoved" class="mb-1 flex items-center justify-between gap-2 rounded-xl bg-gray-100 px-3 py-2 text-sm dark:bg-gray-800" role="status">
      <span>{{ t("people.friendsHub.removed") }}</span>
      <button type="button" class="font-semibold text-brand-600 hover:underline dark:text-brand-300" :disabled="!!busy" data-testid="rail-person-undo" @click="undo">
        {{ t("people.friendsHub.undo") }}
      </button>
    </p>
    <ul class="space-y-1">
      <li
        v-for="p in people.slice(0, MAX_RAIL_PEOPLE)"
        :key="p.account_id"
        class="flex gap-3 rounded-xl p-2 transition hover:bg-gray-200/60 dark:hover:bg-gray-800/60"
        data-testid="rail-person"
        :data-account-id="p.account_id"
      >
        <RouterLink :to="{ name: 'profile-by-id', params: { id: p.account_id } }" class="shrink-0" tabindex="-1" aria-hidden="true">
          <UserAvatar :name="directory.label(p.account_id)" :media-id="directory.avatarOf(p.account_id)" :size="52" />
        </RouterLink>
        <div class="min-w-0 flex-1">
          <RouterLink
            :to="{ name: 'profile-by-id', params: { id: p.account_id } }"
            class="block truncate text-sm font-semibold hover:underline"
            dir="auto"
          >
            {{ directory.label(p.account_id) }}
          </RouterLink>
          <p class="truncate text-xs text-gray-600 dark:text-gray-400" data-testid="rail-person-mutual">
            {{ p.reason === "follows_you" && !p.mutual_count ? t("suggestions.followsYou") : t("suggestions.mutual", p.mutual_count) }}
          </p>
          <div class="mt-2 flex gap-2">
            <button
              v-if="!sent[p.account_id]"
              type="button"
              class="btn-primary flex-1 px-3 py-1.5"
              :disabled="busy === p.account_id"
              data-testid="rail-person-add"
              @click="addFriend(p.account_id)"
            >
              <UserPlus class="h-4 w-4" aria-hidden="true" /> {{ t("suggestions.addFriend") }}
            </button>
            <span
              v-else
              class="btn flex-1 cursor-default bg-brand-50 px-3 py-1.5 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200"
              role="status"
              data-testid="rail-person-sent"
            >
              <Check class="h-4 w-4" aria-hidden="true" /> {{ t("suggestions.requestSent") }}
            </span>
            <button
              v-if="!sent[p.account_id]"
              type="button"
              class="btn flex-1 bg-gray-200 px-3 py-1.5 text-gray-800 hover:bg-gray-300 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
              :disabled="busy === p.account_id"
              :aria-label="t('suggestions.removeLabel', { name: directory.label(p.account_id) })"
              data-testid="rail-person-dismiss"
              @click="dismiss(p.account_id)"
            >
              {{ t("suggestions.remove") }}
            </button>
          </div>
        </div>
      </li>
    </ul>
  </section>
</template>
