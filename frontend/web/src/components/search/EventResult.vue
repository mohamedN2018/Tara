<script setup lang="ts">
import { CalendarDays, MapPin, Users, Video } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { dateBadge, formatRange } from "@/lib/eventTime";
import { useMediaUrl } from "@/lib/useMediaUrl";
import type { SearchResult } from "@/services/search";

const props = defineProps<{ result: SearchResult }>();
const { t, locale } = useI18n();

const cover = useMediaUrl(() => props.result.cover_media_id);
const when = computed(() =>
  props.result.starts_at ? formatRange(props.result.starts_at, props.result.ends_at ?? null, locale.value) : "",
);
const badge = computed(() => (props.result.starts_at ? dateBadge(props.result.starts_at, locale.value) : null));
const online = computed(() => props.result.location_type === "online");
</script>

<template>
  <article class="card flex gap-3 overflow-hidden p-3 sm:p-4" data-testid="event-result">
    <RouterLink
      :to="{ name: 'event', params: { id: result.id } }"
      class="relative h-20 w-20 shrink-0 overflow-hidden rounded-xl bg-tara-gradient-soft sm:h-24 sm:w-32"
      tabindex="-1"
      aria-hidden="true"
    >
      <img v-if="cover" :src="cover" alt="" class="h-full w-full object-cover" loading="lazy" />
      <span v-else class="flex h-full w-full items-center justify-center text-brand-600 dark:text-brand-300">
        <CalendarDays class="h-8 w-8" />
      </span>
      <span v-if="badge" class="absolute start-1.5 top-1.5 rounded-lg bg-white/90 px-1.5 py-0.5 text-center text-[11px] font-bold leading-tight text-brand-700 shadow-sm dark:bg-gray-900/85 dark:text-brand-300">
        {{ badge.day }}<br />{{ badge.month }}
      </span>
    </RouterLink>
    <div class="min-w-0 flex-1">
      <p class="truncate text-xs font-semibold uppercase text-accent-700 dark:text-accent-300">{{ when }}</p>
      <RouterLink
        :to="{ name: 'event', params: { id: result.id } }"
        class="mt-0.5 block truncate font-semibold hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
        dir="auto"
      >
        {{ result.title }}
      </RouterLink>
      <p class="mt-1 flex items-center gap-1 truncate text-xs text-gray-500 dark:text-gray-400">
        <Video v-if="online" class="h-3 w-3 shrink-0" aria-hidden="true" />
        <MapPin v-else class="h-3 w-3 shrink-0" aria-hidden="true" />
        <span class="truncate" dir="auto">{{ online ? t("search.online") : result.location || "—" }}</span>
      </p>
      <p class="mt-0.5 flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
        <Users class="h-3 w-3 shrink-0" aria-hidden="true" />
        {{ t("search.going", result.going_count ?? 0) }}
        <span v-if="result.status === 'cancelled'" class="ms-2 rounded-full bg-red-50 px-2 py-0.5 font-semibold text-red-700 dark:bg-red-950/40 dark:text-red-300">
          {{ t("search.cancelled") }}
        </span>
      </p>
    </div>
  </article>
</template>
