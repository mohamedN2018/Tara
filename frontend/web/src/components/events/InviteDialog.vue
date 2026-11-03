<script setup lang="ts">
import { Check } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { EVENT_ERRORS, eventsService, MAX_INVITES } from "@/services/events";
import { graphService } from "@/services/graph";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

import EventDialog from "./EventDialog.vue";

// The host picks friends to invite. The server checks friendship again (graph)
// and skips people already invited.
const props = defineProps<{ eventId: string }>();
const emit = defineEmits<{ close: []; invited: [ids: string[]] }>();

const { t } = useI18n();
const directory = useDirectoryStore();
const toasts = useToastStore();

const friends = ref<string[]>([]);
const already = ref<Set<string>>(new Set());
const picked = ref<Set<string>>(new Set());
const filter = ref("");
const loading = ref(true);
const sending = ref(false);

const shown = computed(() => {
  const q = filter.value.trim().toLowerCase();
  return q ? friends.value.filter((id) => directory.label(id).toLowerCase().includes(q)) : friends.value;
});

function toggle(id: string) {
  if (already.value.has(id)) return;
  const next = new Set(picked.value);
  if (next.has(id)) next.delete(id);
  else if (next.size < MAX_INVITES) next.add(id);
  picked.value = next;
}

async function load() {
  loading.value = true;
  try {
    const [ids, invited] = await Promise.all([
      graphService.friends(),
      eventsService.attendees(props.eventId, "invited").catch(() => null),
    ]);
    friends.value = ids;
    already.value = new Set((invited?.data ?? []).map((a) => a.account_id));
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
    const invited = await eventsService.invite(props.eventId, ids);
    already.value = new Set([...already.value, ...ids]);
    picked.value = new Set();
    toasts.success(t("events.inviteSent", { count: ids.length }, ids.length));
    emit("invited", invited);
  } catch (e) {
    toasts.error(e, EVENT_ERRORS);
  } finally {
    sending.value = false;
  }
}

onMounted(load);
</script>

<template>
  <EventDialog :title="t('events.inviteTitle')" @close="emit('close')">
    <label class="mb-2 block">
      <span class="sr-only">{{ t("events.inviteSearch") }}</span>
      <input v-model="filter" type="search" class="input" :placeholder="t('events.inviteSearch')" dir="auto" />
    </label>
    <ul class="-mx-1 min-h-24 flex-1 space-y-1 overflow-y-auto" :aria-label="t('events.inviteTitle')">
      <li v-for="id in shown" :key="id">
        <button
          type="button"
          class="flex w-full items-center gap-3 rounded-xl px-2 py-1.5 text-start transition hover:bg-gray-100 disabled:cursor-default dark:hover:bg-gray-800"
          :aria-pressed="picked.has(id) || already.has(id)"
          :disabled="already.has(id)"
          @click="toggle(id)"
        >
          <UserAvatar :name="directory.label(id)" :media-id="directory.avatarOf(id)" :size="36" />
          <span class="min-w-0 flex-1 truncate text-sm font-semibold" dir="auto">{{ directory.label(id) }}</span>
          <span v-if="already.has(id)" class="text-xs text-gray-500 dark:text-gray-400">{{ t("events.invitedBadge") }}</span>
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
      <li v-else-if="!friends.length" class="px-2 py-2 text-sm text-gray-500 dark:text-gray-400">{{ t("events.noFriends") }}</li>
    </ul>
    <button type="button" class="btn-gradient mt-3 w-full" :disabled="!picked.size || sending" @click="send">
      {{ t("events.inviteSend", { count: picked.size }, picked.size) }}
    </button>
  </EventDialog>
</template>
