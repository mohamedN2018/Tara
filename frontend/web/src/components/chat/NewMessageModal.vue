<script setup lang="ts">
// "New message": pick friends to write to. One person opens (or reuses) the
// direct chat with them; two or more start a group chat, which needs a name.
// Only friends are offered here: a stranger's DM starts from their profile and
// lands in their Message requests.
import { Check, Search, X } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import { errorMessage } from "@/lib/errors";
import { foldText } from "@/components/layout/menuCatalog";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { chatService } from "@/services/chat";
import { graphService } from "@/services/graph";
import { useDirectoryStore } from "@/stores/directory";
import type { Conversation } from "@/types";

const emit = defineEmits<{ close: []; done: [conversation: Conversation] }>();

const { t } = useI18n();
const directory = useDirectoryStore();
const open = ref(true);
useEscapeKey(open, () => emit("close"));
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);

const friends = ref<string[]>([]);
const selected = ref<string[]>([]);
const query = ref("");
const title = ref("");
const loading = ref(true);
const submitting = ref(false);
const errorMsg = ref("");

const matches = computed(() => {
  const q = foldText(query.value.trim());
  if (!q) return friends.value;
  return friends.value.filter((id) => foldText(directory.label(id)).includes(q));
});
const isGroup = computed(() => selected.value.length > 1);
const ready = computed(() => selected.value.length > 0 && (!isGroup.value || title.value.trim().length > 0));

function toggle(id: string) {
  selected.value = selected.value.includes(id) ? selected.value.filter((x) => x !== id) : [...selected.value, id];
}

async function submit() {
  if (!ready.value || submitting.value) return;
  submitting.value = true;
  errorMsg.value = "";
  try {
    const conversation = isGroup.value
      ? await chatService.createGroup(title.value.trim(), selected.value)
      : await chatService.openDm(selected.value[0]);
    emit("done", conversation);
  } catch (e) {
    errorMsg.value = errorMessage(e);
  } finally {
    submitting.value = false;
  }
}

onMounted(async () => {
  try {
    friends.value = await graphService.friends();
  } catch (e) {
    errorMsg.value = errorMessage(e);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[60] flex items-end justify-center bg-gray-950/60 p-0 backdrop-blur-sm sm:items-center sm:p-4">
      <div class="fixed inset-0" @click="emit('close')" />
      <form
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-message-title"
        tabindex="-1"
        class="card relative z-10 flex max-h-[92vh] w-full animate-pop-in flex-col overflow-hidden rounded-b-none rounded-t-2xl p-0 shadow-pop sm:max-w-md sm:rounded-2xl"
        data-testid="new-message-dialog"
        @submit.prevent="submit"
      >
        <div class="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-gray-800">
          <h2 id="new-message-title" class="text-lg font-bold">{{ t("messenger.newMessage") }}</h2>
          <button type="button" class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('messages.close')" @click="emit('close')">
            <X class="h-5 w-5" />
          </button>
        </div>

        <!-- "To:" row with the chosen people as chips, then the search field -->
        <div class="border-b border-gray-100 px-4 py-2 dark:border-gray-800">
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="text-sm font-semibold text-gray-600 dark:text-gray-300">{{ t("messenger.to") }}</span>
            <button
              v-for="id in selected"
              :key="id"
              type="button"
              class="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2 py-0.5 text-xs font-semibold text-brand-700 dark:bg-brand-950/60 dark:text-brand-200"
              @click="toggle(id)"
            >
              <span dir="auto">{{ directory.label(id) }}</span>
              <X class="h-3 w-3" aria-hidden="true" />
            </button>
            <label class="relative min-w-[8rem] flex-1">
              <span class="sr-only">{{ t("messenger.searchFriends") }}</span>
              <Search class="pointer-events-none absolute start-2 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden="true" />
              <input
                v-model="query"
                class="w-full rounded-full bg-gray-100 py-1.5 pe-3 ps-8 text-sm outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:bg-gray-800"
                :placeholder="t('messenger.searchFriends')"
                dir="auto"
                data-testid="new-message-search"
              />
            </label>
          </div>
          <div v-if="isGroup" class="mt-2">
            <label for="new-message-group" class="mb-1 block text-xs text-gray-500 dark:text-gray-400">{{ t("messenger.groupNameHint") }}</label>
            <input id="new-message-group" v-model="title" class="input" dir="auto" maxlength="160" :placeholder="t('messages.groupName')" />
          </div>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto p-2">
          <p v-if="loading" class="p-2 text-sm text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
          <EmptyState v-else-if="!friends.length">{{ t("messages.noFriendsToAdd") }}</EmptyState>
          <EmptyState v-else-if="!matches.length">{{ t("messenger.noFriends") }}</EmptyState>
          <ul v-else class="space-y-0.5">
            <li v-for="id in matches" :key="id">
              <button
                type="button"
                class="flex w-full items-center gap-3 rounded-xl px-2 py-1.5 text-start hover:bg-gray-100 dark:hover:bg-gray-800"
                :aria-pressed="selected.includes(id)"
                data-testid="new-message-friend"
                @click="toggle(id)"
              >
                <UserAvatar :name="directory.label(id)" :media-id="directory.avatarOf(id)" :size="36" />
                <span class="min-w-0 flex-1 truncate text-sm font-medium" dir="auto">{{ directory.label(id) }}</span>
                <span
                  class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border"
                  :class="selected.includes(id) ? 'border-brand-600 bg-brand-600 text-white' : 'border-gray-300 dark:border-gray-600'"
                  aria-hidden="true"
                >
                  <Check v-if="selected.includes(id)" class="h-3.5 w-3.5" />
                </span>
              </button>
            </li>
          </ul>
        </div>

        <div class="flex items-center justify-between gap-2 border-t border-gray-100 px-4 py-3 dark:border-gray-800">
          <p v-if="errorMsg" class="text-sm text-red-500">{{ errorMsg }}</p>
          <span v-else class="text-xs text-gray-500 dark:text-gray-400">{{ selected.length ? t("messenger.selected", selected.length) : "" }}</span>
          <button type="submit" class="btn-primary" :disabled="!ready || submitting" data-testid="new-message-start">
            {{ isGroup ? t("messages.createGroup") : t("messenger.startChat") }}
          </button>
        </div>
      </form>
    </div>
  </Teleport>
</template>
