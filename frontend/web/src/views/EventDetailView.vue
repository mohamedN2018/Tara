<script setup lang="ts">
import {
  ArrowLeft,
  Ban,
  CalendarDays,
  Flag,
  Globe2,
  Lock,
  MapPin,
  MoreHorizontal,
  Pencil,
  Share2,
  Trash2,
  UserPlus,
  Users,
  UsersRound,
} from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AttendeesPanel from "@/components/events/AttendeesPanel.vue";
import EventReportDialog from "@/components/events/EventReportDialog.vue";
import InviteDialog from "@/components/events/InviteDialog.vue";
import RsvpControl from "@/components/events/RsvpControl.vue";
import ShareEventDialog from "@/components/events/ShareEventDialog.vue";
import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { httpStatus } from "@/lib/api";
import { dateBadge, formatRange, safeHttpUrl, zoneDiffers, zoneLabel } from "@/lib/eventTime";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useMediaUrl } from "@/lib/useMediaUrl";
import { EVENT_ERRORS, eventsService, type TaraEvent } from "@/services/events";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const directory = useDirectoryStore();
const toasts = useToastStore();

const event = ref<TaraEvent | null>(null);
const loading = ref(true);
const missing = ref(false);
const error = ref(false);
const version = ref(0);
const dialog = ref<"invite" | "report" | "share" | null>(null);
const menuOpen = ref(false);
const busy = ref(false);
useEscapeKey(menuOpen, () => (menuOpen.value = false));

const cover = useMediaUrl(() => event.value?.cover_media_id);
const badge = computed(() => (event.value ? dateBadge(event.value.starts_at, locale.value) : null));
const when = computed(() => (event.value ? formatRange(event.value.starts_at, event.value.ends_at, locale.value) : ""));
const hostTime = computed(() => {
  const e = event.value;
  if (!e || !zoneDiffers(e.timezone, e.starts_at)) return "";
  return t("events.hostTime", {
    time: formatRange(e.starts_at, e.ends_at, locale.value, e.timezone),
    zone: zoneLabel(e.timezone, locale.value, e.starts_at),
  });
});
const link = computed(() => (event.value?.location_type === "online" ? safeHttpUrl(event.value.online_url) : null));
const open = computed(() => event.value?.status === "scheduled");
const AUDIENCE_ICONS = { public: Globe2, friends: Users, invite_only: Lock, group: UsersRound } as const;

async function load() {
  loading.value = true;
  missing.value = false;
  error.value = false;
  try {
    event.value = await eventsService.get(String(route.params.id));
  } catch (e) {
    if (httpStatus(e) === 404) missing.value = true;
    else error.value = true;
  } finally {
    loading.value = false;
  }
}

function changed(updated: TaraEvent) {
  event.value = updated;
  version.value++;
}

async function cancelEvent() {
  menuOpen.value = false;
  if (!event.value || !window.confirm(t("events.cancelConfirm"))) return;
  busy.value = true;
  try {
    changed(await eventsService.cancel(event.value.id));
    toasts.success(t("events.cancelled"));
  } catch (e) {
    toasts.error(e, EVENT_ERRORS);
  } finally {
    busy.value = false;
  }
}

async function deleteEvent() {
  menuOpen.value = false;
  if (!event.value || !window.confirm(t("events.deleteConfirm"))) return;
  busy.value = true;
  try {
    await eventsService.remove(event.value.id);
    toasts.success(t("events.deleted"));
    router.replace("/events?tab=hosting");
  } catch (e) {
    toasts.error(e, EVENT_ERRORS);
  } finally {
    busy.value = false;
  }
}

watch(() => route.params.id, load, { immediate: true });
</script>

<template>
  <AppShell :right="false">
    <div class="mx-auto w-full max-w-[720px] space-y-4">
      <button class="btn-ghost" @click="router.back()">
        <ArrowLeft class="h-4 w-4 rtl:rotate-180" aria-hidden="true" /> {{ t("states.back") }}
      </button>
      <LoadingSkeleton v-if="loading" :rows="3" />
      <EmptyState v-else-if="missing">{{ t("events.notFound") }}</EmptyState>
      <ErrorState v-else-if="error || !event" @retry="load" />
      <template v-else>
        <article class="card overflow-hidden" aria-labelledby="event-title">
          <div class="relative h-44 bg-tara-gradient sm:h-56">
            <img v-if="cover" :src="cover" alt="" class="h-full w-full object-cover" />
            <div v-if="badge" class="absolute start-4 top-4 rounded-xl bg-white/95 px-3.5 py-2 text-center leading-none shadow-card dark:bg-gray-900/95" aria-hidden="true">
              <p class="text-2xl font-extrabold text-brand-600 dark:text-brand-300">{{ badge.day }}</p>
              <p class="mt-1 text-xs font-semibold uppercase text-gray-500 dark:text-gray-400">{{ badge.month }}</p>
            </div>
          </div>

          <div class="space-y-4 p-4 sm:p-6">
            <div class="flex items-start gap-2">
              <div class="min-w-0 flex-1 space-y-1">
                <p v-if="event.status !== 'scheduled'" class="badge bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300">
                  <Ban class="h-3.5 w-3.5" aria-hidden="true" /> {{ t(`events.status.${event.status}`) }}
                </p>
                <h1 id="event-title" class="text-2xl font-extrabold leading-tight" dir="auto">{{ event.title }}</h1>
                <p class="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
                  <component :is="AUDIENCE_ICONS[event.audience]" class="h-3.5 w-3.5" aria-hidden="true" />
                  {{ t(`events.audiences.${event.audience}`) }}
                </p>
              </div>
              <div class="relative">
                <button
                  type="button"
                  class="icon-btn"
                  :aria-label="t('events.more')"
                  :aria-expanded="menuOpen"
                  aria-haspopup="menu"
                  @click="menuOpen = !menuOpen"
                >
                  <MoreHorizontal class="h-5 w-5" aria-hidden="true" />
                </button>
                <div v-if="menuOpen" class="popover absolute end-0 z-20 mt-1 w-56 p-1" role="menu">
                  <template v-if="event.is_host">
                    <RouterLink v-if="open" role="menuitem" :to="`/events/${event.id}/edit`" class="nav-item w-full">
                      <Pencil class="h-4 w-4" aria-hidden="true" /> {{ t("events.edit") }}
                    </RouterLink>
                    <button v-if="open" role="menuitem" type="button" class="nav-item w-full" :disabled="busy" @click="cancelEvent">
                      <Ban class="h-4 w-4" aria-hidden="true" /> {{ t("events.cancel") }}
                    </button>
                    <button role="menuitem" type="button" class="nav-item w-full text-red-600 dark:text-red-400" :disabled="busy" @click="deleteEvent">
                      <Trash2 class="h-4 w-4" aria-hidden="true" /> {{ t("events.delete") }}
                    </button>
                  </template>
                  <button v-else role="menuitem" type="button" class="nav-item w-full" @click="menuOpen = false; dialog = 'report'">
                    <Flag class="h-4 w-4" aria-hidden="true" /> {{ t("events.report") }}
                  </button>
                </div>
              </div>
            </div>

            <RouterLink :to="{ name: 'profile-by-id', params: { id: event.host_id } }" class="flex w-fit items-center gap-2 rounded-xl pe-2 transition hover:bg-gray-100 dark:hover:bg-gray-800">
              <UserAvatar :name="directory.label(event.host_id)" :media-id="directory.avatarOf(event.host_id)" :size="36" />
              <span class="text-sm">
                <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t("events.host") }}</span>
                <span class="font-semibold" dir="auto">{{ directory.label(event.host_id) }}</span>
              </span>
            </RouterLink>

            <dl class="space-y-2 text-sm">
              <div class="flex items-start gap-2">
                <dt class="sr-only">{{ t("events.form.when") }}</dt>
                <CalendarDays class="mt-0.5 h-4 w-4 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
                <dd>
                  <span class="font-semibold">{{ when }}</span>
                  <span v-if="hostTime" class="block text-xs text-gray-500 dark:text-gray-400">{{ hostTime }}</span>
                </dd>
              </div>
              <div class="flex items-start gap-2">
                <dt class="sr-only">{{ t("events.form.where") }}</dt>
                <Globe2 v-if="event.location_type === 'online'" class="mt-0.5 h-4 w-4 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
                <MapPin v-else class="mt-0.5 h-4 w-4 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
                <dd class="min-w-0">
                  <template v-if="event.location_type === 'online'">
                    <span class="block">{{ t("events.online") }}</span>
                    <a v-if="link" :href="link" target="_blank" rel="noopener noreferrer nofollow" class="block truncate text-brand-600 underline dark:text-brand-300" dir="ltr">{{ link }}</a>
                  </template>
                  <span v-else dir="auto">{{ event.location }}</span>
                </dd>
              </div>
              <div class="flex items-start gap-2">
                <dt class="sr-only">{{ t("events.people") }}</dt>
                <Users class="mt-0.5 h-4 w-4 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
                <dd>
                  {{ t("events.counts.going", { count: event.going_count }, event.going_count) }}
                  <span aria-hidden="true"> · </span>
                  {{ t("events.counts.interested", { count: event.interested_count }, event.interested_count) }}
                  <template v-if="event.spots_left !== null">
                    <span aria-hidden="true"> · </span>
                    <span :class="event.spots_left === 0 ? 'font-semibold text-red-600 dark:text-red-400' : ''">
                      {{ t("events.counts.spotsLeft", { count: event.spots_left }, event.spots_left) }}
                    </span>
                  </template>
                </dd>
              </div>
            </dl>

            <p v-if="event.invited && !event.my_rsvp && !event.is_host" class="rounded-xl bg-brand-50 px-3 py-2 text-sm text-brand-800 dark:bg-brand-950/50 dark:text-brand-200">
              {{ t("events.invitedBanner") }}
            </p>

            <RsvpControl v-if="open && !event.is_host" :event="event" @changed="changed" />

            <div class="flex flex-wrap gap-2">
              <button v-if="event.is_host && open" type="button" class="btn-soft" @click="dialog = 'invite'">
                <UserPlus class="h-4 w-4" aria-hidden="true" /> {{ t("events.invite") }}
              </button>
              <button v-if="open" type="button" class="btn-ghost" @click="dialog = 'share'">
                <Share2 class="h-4 w-4" aria-hidden="true" /> {{ t("events.share") }}
              </button>
            </div>

            <section v-if="event.description" aria-labelledby="event-details-title">
              <h2 id="event-details-title" class="mb-1 font-bold">{{ t("events.details") }}</h2>
              <p class="whitespace-pre-line break-words text-sm leading-relaxed" dir="auto">{{ event.description }}</p>
            </section>
          </div>
        </article>

        <AttendeesPanel :event="event" :version="version" />
      </template>
    </div>

    <InviteDialog v-if="dialog === 'invite' && event" :event-id="event.id" @close="dialog = null" @invited="version++" />
    <EventReportDialog v-if="dialog === 'report' && event" :event-id="event.id" @close="dialog = null" @reported="dialog = null" />
    <ShareEventDialog v-if="dialog === 'share' && event" :event="event" @close="dialog = null" />
  </AppShell>
</template>
