<script setup lang="ts">
import { Check, Undo2, UserPlus } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

import type { PersonSuggestion } from "@/services/relationships";
import { useDirectoryStore } from "@/stores/directory";

import PersonPhoto from "./PersonPhoto.vue";

// One "People you may know" photo card: Add friend / Remove, then Cancel
// request or Undo once acted on. The parent owns the calls and the state.
defineProps<{ person: PersonSuggestion; state: "idle" | "sent" | "dismissed"; busy?: boolean }>();
const emit = defineEmits<{ add: []; cancel: []; remove: []; undo: [] }>();
const { t } = useI18n();
const directory = useDirectoryStore();
</script>

<template>
  <li class="card flex flex-col overflow-hidden" data-testid="friend-suggestion-card" :data-account-id="person.account_id">
    <PersonPhoto :account-id="person.account_id" />
    <div class="flex flex-1 flex-col gap-2 p-3">
      <RouterLink :to="{ name: 'profile-by-id', params: { id: person.account_id } }" class="truncate text-start font-semibold hover:underline">
        <bdi>{{ directory.label(person.account_id) }}</bdi>
      </RouterLink>
      <p class="-mt-1 truncate text-xs text-gray-600 dark:text-gray-400">
        {{ person.reason === "follows_you" && !person.mutual_count ? t("people.friendsHub.followsYou") : t("people.hero.mutual", person.mutual_count) }}
      </p>
      <template v-if="state === 'dismissed'">
        <p class="text-sm text-gray-600 dark:text-gray-300" role="status">{{ t("people.friendsHub.removed") }}</p>
        <button type="button" class="btn-soft w-full justify-center py-1.5" :disabled="busy" @click="emit('undo')">
          <Undo2 class="h-4 w-4" aria-hidden="true" /> {{ t("people.friendsHub.undo") }}
        </button>
      </template>
      <template v-else-if="state === 'sent'">
        <span class="btn w-full cursor-default justify-center bg-brand-50 py-1.5 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200" role="status">
          <Check class="h-4 w-4" aria-hidden="true" /> {{ t("people.friendsHub.requestSent") }}
        </span>
        <button type="button" class="btn-soft w-full justify-center py-1.5" :disabled="busy" @click="emit('cancel')">
          {{ t("people.friendsHub.cancelRequest") }}
        </button>
      </template>
      <template v-else>
        <button type="button" class="btn-primary w-full justify-center py-1.5" :disabled="busy" data-testid="suggestion-add" @click="emit('add')">
          <UserPlus class="h-4 w-4" aria-hidden="true" /> {{ t("people.friendsHub.addFriend") }}
        </button>
        <button type="button" class="btn-soft w-full justify-center py-1.5" :disabled="busy" data-testid="suggestion-remove" @click="emit('remove')">
          {{ t("people.friendsHub.remove") }}
        </button>
      </template>
    </div>
  </li>
</template>
