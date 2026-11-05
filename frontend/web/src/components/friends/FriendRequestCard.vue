<script setup lang="ts">
import { useI18n } from "vue-i18n";

import { useDirectoryStore } from "@/stores/directory";

import PersonPhoto from "./PersonPhoto.vue";

// One incoming friend request as a photo card: Confirm / Delete.
defineProps<{ accountId: string; busy?: boolean }>();
const emit = defineEmits<{ confirm: []; delete: [] }>();
const { t } = useI18n();
const directory = useDirectoryStore();
</script>

<template>
  <li class="card flex flex-col overflow-hidden" data-testid="friend-request-card" :data-account-id="accountId">
    <PersonPhoto :account-id="accountId" />
    <div class="flex flex-1 flex-col gap-2 p-3">
      <RouterLink :to="{ name: 'profile-by-id', params: { id: accountId } }" class="truncate text-start font-semibold hover:underline">
        <bdi>{{ directory.label(accountId) }}</bdi>
      </RouterLink>
      <button type="button" class="btn-primary w-full justify-center py-1.5" :disabled="busy" @click="emit('confirm')">
        {{ t("people.friendsHub.confirm") }}
      </button>
      <button type="button" class="btn-soft w-full justify-center py-1.5" :disabled="busy" @click="emit('delete')">
        {{ t("people.friendsHub.delete") }}
      </button>
    </div>
  </li>
</template>
