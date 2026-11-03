<script setup lang="ts">
import { CalendarDays, Globe2, MapPin } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { dateBadge, formatRange } from "@/lib/eventTime";
import { useMediaUrl } from "@/lib/useMediaUrl";
import type { TaraEvent } from "@/services/events";
import { useDirectoryStore } from "@/stores/directory";

const props = defineProps<{ event: TaraEvent }>();

const { t, locale } = useI18n();
const directory = useDirectoryStore();
const cover = useMediaUrl(() => props.event.cover_media_id);
const badge = computed(() => dateBadge(props.event.starts_at, locale.value));
const when = computed(() => formatRange(props.event.starts_at, props.event.ends_at, locale.value));
const titleId = computed(() => `event-card-${props.event.id}`);
const stateLabel = computed(() => {
  const e = props.event;
  if (e.status !== "scheduled") return t(`events.status.${e.status}`);
  if (e.is_host) return t("events.youHost");
  if (e.my_rsvp) return t(`events.rsvp.${e.my_rsvp}`);
  if (e.invited) return t("events.invitedBadge");
  return "";
});
</script>

<template>
  <article class="card card-hover overflow-hidden" :aria-labelledby="titleId" :class="event.status !== 'scheduled' ? 'opacity-80' : ''">
    <RouterLink :to="`/events/${event.id}`" class="block focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400">
      <div class="relative h-32 bg-tara-gradient">
        <img v-if="cover" :src="cover" alt="" class="h-full w-full object-cover" loading="lazy" />
        <div class="absolute start-3 top-3 rounded-xl bg-white/95 px-3 py-1.5 text-center leading-none shadow-card dark:bg-gray-900/95" aria-hidden="true">
          <p class="text-lg font-extrabold text-brand-600 dark:text-brand-300">{{ badge.day }}</p>
          <p class="mt-0.5 text-[11px] font-semibold uppercase text-gray-500 dark:text-gray-400">{{ badge.month }}</p>
        </div>
        <span
          v-if="stateLabel"
          class="badge absolute end-3 top-3 bg-white/95 text-gray-800 shadow-card dark:bg-gray-900/95 dark:text-gray-100"
          :class="event.status === 'cancelled' ? '!text-red-600 dark:!text-red-400' : ''"
        >
          {{ stateLabel }}
        </span>
      </div>
      <div class="space-y-1.5 p-4">
        <h3 :id="titleId" class="line-clamp-2 font-bold" dir="auto">{{ event.title }}</h3>
        <p class="flex items-center gap-1.5 text-sm text-brand-700 dark:text-brand-300">
          <CalendarDays class="h-4 w-4 shrink-0" aria-hidden="true" />
          <span class="truncate">{{ when }}</span>
        </p>
        <p class="flex items-center gap-1.5 text-sm text-gray-600 dark:text-gray-300">
          <Globe2 v-if="event.location_type === 'online'" class="h-4 w-4 shrink-0" aria-hidden="true" />
          <MapPin v-else class="h-4 w-4 shrink-0" aria-hidden="true" />
          <span class="truncate" dir="auto">{{ event.location_type === "online" ? t("events.online") : event.location }}</span>
        </p>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          <span dir="auto">{{ t("events.hostedBy", { name: directory.label(event.host_id) }) }}</span>
          <span aria-hidden="true"> · </span>
          <span>{{ t("events.counts.going", { count: event.going_count }, event.going_count) }}</span>
        </p>
      </div>
    </RouterLink>
  </article>
</template>
