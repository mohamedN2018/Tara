<script setup lang="ts">
import { CalendarCheck, Star, X } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { httpStatus } from "@/lib/api";
import { EVENT_ERRORS, eventsService, RSVP_STATES, type RsvpStatus, type TaraEvent } from "@/services/events";
import { useToastStore } from "@/stores/toasts";

// Going / Interested / Can't go, as a toggle group. Pressing the current answer
// again takes it back. The server enforces capacity (409 event_full).
const props = defineProps<{ event: TaraEvent }>();
const emit = defineEmits<{ changed: [event: TaraEvent] }>();

const { t } = useI18n();
const toasts = useToastStore();
const busy = ref(false);
const ICONS = { going: CalendarCheck, interested: Star, not_going: X } as const;

const full = computed(() => props.event.spots_left === 0 && props.event.my_rsvp !== "going");

async function choose(status: RsvpStatus) {
  if (busy.value) return;
  busy.value = true;
  try {
    const updated =
      props.event.my_rsvp === status
        ? await eventsService.withdraw(props.event.id)
        : await eventsService.rsvp(props.event.id, status);
    emit("changed", updated);
  } catch (e) {
    toasts.error(e, EVENT_ERRORS);
    if (httpStatus(e) === 409) {
      // Full or cancelled since the page loaded: show the current state.
      eventsService.get(props.event.id).then((fresh) => emit("changed", fresh)).catch(() => {});
    }
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="flex flex-wrap gap-2" role="group" :aria-label="t('events.rsvp.label')">
    <button
      v-for="s in RSVP_STATES"
      :key="s"
      type="button"
      class="btn flex-1 border"
      :class="
        event.my_rsvp === s
          ? 'border-brand-600 bg-brand-600 text-white shadow-sm hover:bg-brand-700'
          : 'border-gray-200 text-gray-700 hover:bg-gray-100 dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800'
      "
      :aria-pressed="event.my_rsvp === s"
      :disabled="busy || (s === 'going' && full)"
      @click="choose(s)"
    >
      <component :is="ICONS[s]" class="h-4 w-4" aria-hidden="true" />
      {{ s === "going" && full ? t("events.rsvp.full") : t(`events.rsvp.${s}`) }}
    </button>
  </div>
</template>
