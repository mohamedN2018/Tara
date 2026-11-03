<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { type Attendee, type AttendeeState, eventsService, type TaraEvent } from "@/services/events";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

// People by answer. "Can't go" and "Invited" are the host's lists only. The
// server leaves out accounts blocked either way.
const props = defineProps<{ event: TaraEvent; version: number }>();

const { t } = useI18n();
const directory = useDirectoryStore();
const toasts = useToastStore();

const tabs = computed<AttendeeState[]>(() =>
  props.event.is_host ? ["going", "interested", "not_going", "invited"] : ["going", "interested"],
);
const active = ref<AttendeeState>("going");
const items = ref<Attendee[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(false);
let generation = 0;

const count = (state: AttendeeState) =>
  state === "going" ? props.event.going_count : state === "interested" ? props.event.interested_count : null;

async function load(reset: boolean) {
  const mine = reset ? ++generation : generation;
  loading.value = true;
  try {
    const page = await eventsService.attendees(props.event.id, active.value, reset ? null : cursor.value);
    if (mine !== generation) return;
    items.value = reset ? page.data : [...items.value, ...page.data];
    cursor.value = page.page.next_cursor;
  } catch (e) {
    if (mine === generation) toasts.error(e);
  } finally {
    if (mine === generation) loading.value = false;
  }
}

function pick(state: AttendeeState) {
  if (active.value === state) return;
  active.value = state;
}

watch([active, () => props.version], () => load(true), { immediate: true });
</script>

<template>
  <section class="card p-4" aria-labelledby="event-people-title">
    <h2 id="event-people-title" class="mb-3 font-bold">{{ t("events.people") }}</h2>
    <div class="mb-3 flex gap-1.5 overflow-x-auto pb-1" role="tablist" :aria-label="t('events.people')">
      <button
        v-for="s in tabs"
        :key="s"
        role="tab"
        type="button"
        class="chip shrink-0"
        :class="active === s ? 'chip-active' : ''"
        :aria-selected="active === s"
        @click="pick(s)"
      >
        {{ t(`events.attendeeTabs.${s}`) }}
        <span v-if="count(s) !== null" class="tabular-nums">{{ count(s) }}</span>
      </button>
    </div>
    <ul class="-mx-1 space-y-1" role="tabpanel">
      <li v-for="a in items" :key="a.account_id">
        <RouterLink
          :to="{ name: 'profile-by-id', params: { id: a.account_id } }"
          class="flex items-center gap-3 rounded-xl px-2 py-1.5 transition hover:bg-gray-100 dark:hover:bg-gray-800"
        >
          <UserAvatar :name="directory.label(a.account_id)" :media-id="directory.avatarOf(a.account_id)" :size="36" />
          <span class="min-w-0 truncate text-sm font-semibold" dir="auto">{{ directory.label(a.account_id) }}</span>
        </RouterLink>
      </li>
      <li v-if="loading" class="px-2 py-2 text-xs text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</li>
      <li v-else-if="!items.length" class="px-2 py-2 text-sm text-gray-500 dark:text-gray-400">{{ t("events.noPeople") }}</li>
    </ul>
    <button v-if="cursor && !loading" type="button" class="btn-ghost mt-2 w-full" @click="load(false)">{{ t("states.loadMore") }}</button>
  </section>
</template>
