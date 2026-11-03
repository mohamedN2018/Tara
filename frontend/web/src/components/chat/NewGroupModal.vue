<script setup lang="ts">
import { X } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import { errorMessage } from "@/lib/errors";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { chatService } from "@/services/chat";
import { graphService } from "@/services/graph";
import { useDirectoryStore } from "@/stores/directory";
import type { Conversation } from "@/types";

// With `conversation` it adds members to that group; without, it creates one.
const props = defineProps<{ conversation?: Conversation | null }>();
const emit = defineEmits<{ close: []; done: [conversation: Conversation] }>();

const { t } = useI18n();
const directory = useDirectoryStore();
const open = ref(true);
useEscapeKey(open, () => emit("close"));
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);

const friends = ref<string[]>([]);
const selected = ref<Set<string>>(new Set());
const title = ref("");
const loading = ref(true);
const submitting = ref(false);
const errorMsg = ref("");

const adding = computed(() => !!props.conversation);
const candidates = computed(() => {
  const existing = new Set(props.conversation?.members ?? []);
  return friends.value.filter((id) => !existing.has(id));
});
const ready = computed(() => selected.value.size > 0 && (adding.value || title.value.trim().length > 0));

function toggle(id: string) {
  if (selected.value.has(id)) selected.value.delete(id);
  else selected.value.add(id);
}

async function submit() {
  if (!ready.value || submitting.value) return;
  submitting.value = true;
  errorMsg.value = "";
  try {
    const ids = [...selected.value];
    const conversation = props.conversation
      ? await chatService.addMembers(props.conversation.id, ids)
      : await chatService.createGroup(title.value.trim(), ids);
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
  <div class="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4">
    <div class="fixed inset-0" @click="emit('close')" />
    <div
      ref="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="group-dialog-title"
      tabindex="-1"
      class="card relative z-10 max-h-[92vh] w-full overflow-y-auto rounded-b-none rounded-t-2xl p-4 sm:max-w-md sm:rounded-2xl sm:p-5"
    >
      <div class="mb-4 flex items-center justify-between">
        <h2 id="group-dialog-title" class="text-lg font-bold">
          {{ adding ? t("messages.addMembers") : t("messages.newGroup") }}
        </h2>
        <button class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('market.close')" @click="emit('close')">
          <X class="h-5 w-5" />
        </button>
      </div>

      <form class="space-y-3" @submit.prevent="submit">
        <div v-if="!adding">
          <label for="group-title" class="mb-1 block text-sm font-medium">{{ t("messages.groupName") }}</label>
          <input id="group-title" v-model="title" class="input" dir="auto" maxlength="160" required />
        </div>

        <fieldset>
          <legend class="mb-1 text-sm font-medium">{{ t("messages.chooseFriends") }}</legend>
          <p v-if="loading" class="text-sm text-gray-400">{{ t("states.loading") }}</p>
          <EmptyState v-else-if="!candidates.length">{{ t("messages.noFriendsToAdd") }}</EmptyState>
          <ul v-else class="max-h-64 space-y-1 overflow-y-auto">
            <li v-for="id in candidates" :key="id">
              <label class="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-800/60">
                <input type="checkbox" class="h-4 w-4 accent-brand-600" :checked="selected.has(id)" @change="toggle(id)" />
                <UserAvatar :name="directory.label(id)" :media-id="directory.avatarOf(id)" :size="32" />
                <span class="min-w-0 truncate text-sm" dir="auto">{{ directory.label(id) }}</span>
              </label>
            </li>
          </ul>
        </fieldset>

        <p v-if="errorMsg" class="text-sm text-red-500">{{ errorMsg }}</p>
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="emit('close')">{{ t("feed.cancel") }}</button>
          <button type="submit" class="btn-primary" :disabled="!ready || submitting">
            {{ adding ? t("messages.add") : t("messages.createGroup") }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
