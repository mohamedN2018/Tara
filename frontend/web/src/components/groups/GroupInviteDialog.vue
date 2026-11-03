<script setup lang="ts">
import { Check } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import EventDialog from "@/components/events/EventDialog.vue";
import { GROUP_ERRORS, groupsService, MAX_INVITES } from "@/services/groups";
import { graphService } from "@/services/graph";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

// Invite friends. The server checks friendship again (graph) and skips people
// already in the group, invited or banned.
const props = defineProps<{ groupRef: string }>();
const emit = defineEmits<{ close: []; invited: [ids: string[]] }>();

const { t } = useI18n();
const directory = useDirectoryStore();
const toasts = useToastStore();

const friends = ref<string[]>([]);
const done = ref<Set<string>>(new Set());
const picked = ref<Set<string>>(new Set());
const filter = ref("");
const loading = ref(true);
const sending = ref(false);

const shown = computed(() => {
  const q = filter.value.trim().toLowerCase();
  return q ? friends.value.filter((id) => directory.label(id).toLowerCase().includes(q)) : friends.value;
});

function toggle(id: string) {
  if (done.value.has(id)) return;
  const next = new Set(picked.value);
  if (next.has(id)) next.delete(id);
  else if (next.size < MAX_INVITES) next.add(id);
  picked.value = next;
}

async function load() {
  loading.value = true;
  try {
    friends.value = await graphService.friends();
  } catch (e) {
    toasts.error(e);
  } finally {
    loading.value = false;
  }
}

async function send() {
  if (!picked.value.size || sending.value) return;
  sending.value = true;
  try {
    const ids = [...picked.value];
    const invited = await groupsService.invite(props.groupRef, ids);
    done.value = new Set([...done.value, ...ids]);
    picked.value = new Set();
    toasts.success(t("groups.invite.sent", { count: ids.length }, ids.length));
    emit("invited", invited);
  } catch (e) {
    toasts.error(e, GROUP_ERRORS);
  } finally {
    sending.value = false;
  }
}

onMounted(load);
</script>

<template>
  <EventDialog :title="t('groups.invite.title')" @close="emit('close')">
    <label class="mb-2 block">
      <span class="sr-only">{{ t("groups.invite.search") }}</span>
      <input v-model="filter" type="search" class="input" :placeholder="t('groups.invite.search')" dir="auto" />
    </label>
    <ul class="-mx-1 min-h-24 flex-1 space-y-1 overflow-y-auto" :aria-label="t('groups.invite.title')">
      <li v-for="id in shown" :key="id">
        <button
          type="button"
          class="flex w-full items-center gap-3 rounded-xl px-2 py-1.5 text-start transition hover:bg-gray-100 disabled:cursor-default dark:hover:bg-gray-800"
          :aria-pressed="picked.has(id) || done.has(id)"
          :disabled="done.has(id)"
          @click="toggle(id)"
        >
          <UserAvatar :name="directory.label(id)" :media-id="directory.avatarOf(id)" :size="36" />
          <span class="min-w-0 flex-1 truncate text-sm font-semibold" dir="auto">{{ directory.label(id) }}</span>
          <span v-if="done.has(id)" class="text-xs text-gray-500 dark:text-gray-400">{{ t("groups.invite.invitedBadge") }}</span>
          <span
            v-else
            class="flex h-5 w-5 items-center justify-center rounded-md border"
            :class="picked.has(id) ? 'border-brand-600 bg-brand-600 text-white' : 'border-gray-300 dark:border-gray-700'"
            aria-hidden="true"
          >
            <Check v-if="picked.has(id)" class="h-3.5 w-3.5" />
          </span>
        </button>
      </li>
      <li v-if="loading" class="px-2 py-2 text-xs text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</li>
      <li v-else-if="!friends.length" class="px-2 py-2 text-sm text-gray-500 dark:text-gray-400">{{ t("groups.invite.noFriends") }}</li>
    </ul>
    <button type="button" class="btn-gradient mt-3 w-full" :disabled="!picked.size || sending" @click="send">
      {{ picked.size ? t("groups.invite.send", { count: picked.size }, picked.size) : t("groups.invite.button") }}
    </button>
  </EventDialog>
</template>
