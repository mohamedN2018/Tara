<script setup lang="ts">
import { ArrowLeft, Globe2, ImagePlus, Lock, MapPin, Trash2, Users } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { mediaErrorKey } from "@/lib/errors";
import { fromInputParts, safeHttpUrl, toInputParts, viewerTimeZone } from "@/lib/eventTime";
import { useMediaUrl } from "@/lib/useMediaUrl";
import {
  EVENT_AUDIENCES,
  EVENT_ERRORS,
  type EventAudience,
  type EventInput,
  eventsService,
  type LocationType,
  MAX_DESCRIPTION,
  MAX_TITLE,
  type TaraEvent,
} from "@/services/events";
import { mediaService } from "@/services/media";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const toasts = useToastStore();

const editingId = computed(() => (route.name === "event-edit" ? String(route.params.id) : null));
const original = ref<TaraEvent | null>(null);
const loading = ref(false);
const loadError = ref(false);
const saving = ref(false);
const uploading = ref(false);
const formError = ref("");

const title = ref("");
const description = ref("");
const startDate = ref("");
const startTime = ref("");
const hasEnd = ref(false);
const endDate = ref("");
const endTime = ref("");
const locationType = ref<LocationType>("place");
const location = ref("");
const onlineUrl = ref("");
const coverId = ref<string | null>(null);
const audience = ref<EventAudience>("public");
// A number input: Vue hands back a number once something is typed.
const capacity = ref<string | number>("");
const zone = viewerTimeZone();
const coverUrl = useMediaUrl(() => coverId.value);

const AUDIENCE_ICONS = { public: Globe2, friends: Users, invite_only: Lock } as const;

function defaults() {
  // Tomorrow at 19:00 in the viewer's zone.
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(19, 0, 0, 0);
  const parts = toInputParts(d.toISOString());
  startDate.value = parts.date;
  startTime.value = parts.time;
}

function fill(e: TaraEvent) {
  title.value = e.title;
  description.value = e.description;
  ({ date: startDate.value, time: startTime.value } = toInputParts(e.starts_at));
  hasEnd.value = !!e.ends_at;
  ({ date: endDate.value, time: endTime.value } = toInputParts(e.ends_at));
  locationType.value = e.location_type;
  location.value = e.location;
  onlineUrl.value = e.online_url;
  coverId.value = e.cover_media_id;
  audience.value = e.audience;
  capacity.value = e.capacity === null ? "" : String(e.capacity);
}

async function load() {
  if (!editingId.value) {
    defaults();
    return;
  }
  loading.value = true;
  loadError.value = false;
  try {
    const e = await eventsService.get(editingId.value);
    if (!e.is_host) {
      router.replace(`/events/${e.id}`);
      return;
    }
    original.value = e;
    fill(e);
  } catch {
    loadError.value = true;
  } finally {
    loading.value = false;
  }
}

async function onCover(ev: Event) {
  const input = ev.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  uploading.value = true;
  try {
    coverId.value = (await mediaService.upload(file, "image")).id;
  } catch (e) {
    toasts.error(e, { request_failed: "errors.uploadFailed" });
  } finally {
    uploading.value = false;
  }
}

function toggleEnd() {
  hasEnd.value = !hasEnd.value;
  if (hasEnd.value && !endDate.value) {
    endDate.value = startDate.value;
    endTime.value = startTime.value;
  }
}

/** The form as the API's input, or a message key for what is wrong. */
function build(): EventInput | string {
  if (!title.value.trim()) return "events.form.titleRequired";
  const starts = fromInputParts(startDate.value, startTime.value);
  if (!starts) return "events.form.invalidStart";
  let ends: string | null = null;
  if (hasEnd.value) {
    ends = fromInputParts(endDate.value, endTime.value);
    if (!ends) return "events.form.invalidEnd";
    if (new Date(ends) < new Date(starts)) return "events.errors.ends_before_start";
  }
  if (locationType.value === "place" && !location.value.trim()) return "events.errors.location_required";
  if (locationType.value === "online" && !safeHttpUrl(onlineUrl.value.trim())) return "events.errors.invalid_url";
  const rawCapacity = String(capacity.value ?? "").trim();
  const cap = rawCapacity ? Number(rawCapacity) : null;
  if (cap !== null && (!Number.isInteger(cap) || cap < 1)) return "events.form.invalidCapacity";
  return {
    title: title.value.trim(),
    description: description.value,
    starts_at: starts,
    ends_at: ends,
    timezone: zone,
    location_type: locationType.value,
    location: locationType.value === "place" ? location.value.trim() : "",
    online_url: locationType.value === "online" ? onlineUrl.value.trim() : "",
    cover_media_id: coverId.value,
    audience: audience.value,
    capacity: cap,
  };
}

/** Only what changed, so an untouched time never looks like a move. */
function changes(input: EventInput, e: TaraEvent): Partial<EventInput> {
  const out: Partial<EventInput> = {};
  const same = (a: string | null, b: string | null) => (a && b ? new Date(a).getTime() === new Date(b).getTime() : a === b);
  for (const key of Object.keys(input) as (keyof EventInput)[]) {
    const before = e[key as keyof TaraEvent] as unknown;
    const after = input[key] as unknown;
    const equal =
      key === "starts_at" || key === "ends_at" ? same(after as string | null, before as string | null) : after === before;
    if (!equal) (out as Record<string, unknown>)[key] = after;
  }
  // The zone only matters with a new time.
  if (!("starts_at" in out) && !("ends_at" in out)) delete out.timezone;
  return out;
}

async function submit() {
  formError.value = "";
  const input = build();
  if (typeof input === "string") {
    formError.value = t(input);
    return;
  }
  saving.value = true;
  try {
    let saved: TaraEvent;
    if (original.value) {
      const diff = changes(input, original.value);
      saved = Object.keys(diff).length ? await eventsService.update(original.value.id, diff) : original.value;
    } else {
      saved = await eventsService.create(input);
    }
    toasts.success(t(original.value ? "events.form.saved" : "events.form.created"));
    router.push(`/events/${saved.id}`);
  } catch (e) {
    const media = mediaErrorKey(e);
    if (media) toasts.push({ text: t(media), icon: "error" });
    else toasts.error(e, EVENT_ERRORS);
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <AppShell :right="false">
    <div class="mx-auto w-full max-w-[640px] space-y-4">
      <button class="btn-ghost" @click="router.back()">
        <ArrowLeft class="h-4 w-4 rtl:rotate-180" aria-hidden="true" /> {{ t("states.back") }}
      </button>
      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="loadError" @retry="load" />
      <form v-else class="card space-y-5 p-4 sm:p-6" novalidate @submit.prevent="submit">
        <h1 class="text-xl font-bold">{{ t(editingId ? "events.editTitle" : "events.newTitle") }}</h1>

        <!-- Cover -->
        <div>
          <p class="label">{{ t("events.form.cover") }}</p>
          <div class="relative mt-1 h-40 overflow-hidden rounded-xl bg-tara-gradient">
            <img v-if="coverUrl" :src="coverUrl" alt="" class="h-full w-full object-cover" />
            <div class="absolute inset-x-0 bottom-0 flex justify-end gap-2 p-2">
              <label class="btn-soft cursor-pointer bg-white/90 dark:bg-gray-900/90" :class="uploading ? 'pointer-events-none opacity-60' : ''">
                <ImagePlus class="h-4 w-4" aria-hidden="true" />
                {{ uploading ? t("events.form.uploading") : coverId ? t("events.form.changeCover") : t("events.form.addCover") }}
                <input type="file" accept="image/*" class="sr-only" :disabled="uploading" @change="onCover" />
              </label>
              <button v-if="coverId" type="button" class="btn-soft bg-white/90 dark:bg-gray-900/90" :aria-label="t('events.form.removeCover')" @click="coverId = null">
                <Trash2 class="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>

        <div>
          <label for="event-title" class="label">{{ t("events.form.title") }}</label>
          <input id="event-title" v-model="title" class="input" :maxlength="MAX_TITLE" required dir="auto" autocomplete="off" />
        </div>

        <!-- When: separate date and time inputs, left-to-right even in RTL -->
        <fieldset class="space-y-3">
          <legend class="label">{{ t("events.form.when") }}</legend>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label for="event-start-date" class="text-xs text-gray-500 dark:text-gray-400">{{ t("events.form.startDate") }}</label>
              <input id="event-start-date" v-model="startDate" type="date" class="input" dir="ltr" required />
            </div>
            <div>
              <label for="event-start-time" class="text-xs text-gray-500 dark:text-gray-400">{{ t("events.form.startTime") }}</label>
              <input id="event-start-time" v-model="startTime" type="time" class="input" dir="ltr" required />
            </div>
          </div>
          <div v-if="hasEnd" class="grid grid-cols-2 gap-3">
            <div>
              <label for="event-end-date" class="text-xs text-gray-500 dark:text-gray-400">{{ t("events.form.endDate") }}</label>
              <input id="event-end-date" v-model="endDate" type="date" class="input" dir="ltr" :min="startDate" />
            </div>
            <div>
              <label for="event-end-time" class="text-xs text-gray-500 dark:text-gray-400">{{ t("events.form.endTime") }}</label>
              <input id="event-end-time" v-model="endTime" type="time" class="input" dir="ltr" />
            </div>
          </div>
          <div class="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              class="btn-ghost px-2 py-1 text-xs"
              @click="toggleEnd"
            >
              {{ hasEnd ? t("events.form.removeEnd") : t("events.form.addEnd") }}
            </button>
            <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("events.form.zoneNote", { zone }) }}</p>
          </div>
        </fieldset>

        <!-- Where -->
        <fieldset>
          <legend class="label">{{ t("events.form.where") }}</legend>
          <div class="mt-1 flex gap-2" role="radiogroup" :aria-label="t('events.form.where')">
            <label v-for="kind in (['place', 'online'] as LocationType[])" :key="kind" class="chip cursor-pointer" :class="locationType === kind ? 'chip-active' : ''">
              <input v-model="locationType" type="radio" class="sr-only" name="location-type" :value="kind" />
              <MapPin v-if="kind === 'place'" class="h-4 w-4" aria-hidden="true" />
              <Globe2 v-else class="h-4 w-4" aria-hidden="true" />
              {{ t(`events.form.${kind}`) }}
            </label>
          </div>
          <div class="mt-3">
            <template v-if="locationType === 'place'">
              <label for="event-location" class="sr-only">{{ t("events.form.location") }}</label>
              <input id="event-location" v-model="location" class="input" maxlength="255" dir="auto" :placeholder="t('events.form.locationPlaceholder')" />
            </template>
            <template v-else>
              <label for="event-url" class="sr-only">{{ t("events.form.onlineUrl") }}</label>
              <input id="event-url" v-model="onlineUrl" type="url" inputmode="url" class="input" maxlength="500" dir="ltr" placeholder="https://" />
            </template>
          </div>
        </fieldset>

        <div>
          <label for="event-description" class="label">{{ t("events.form.description") }}</label>
          <textarea id="event-description" v-model="description" class="input min-h-28" rows="4" :maxlength="MAX_DESCRIPTION" dir="auto" />
          <p class="mt-1 text-end text-xs tabular-nums text-gray-500 dark:text-gray-400">{{ description.length }} / {{ MAX_DESCRIPTION }}</p>
        </div>

        <fieldset>
          <legend class="label">{{ t("events.form.audience") }}</legend>
          <div class="mt-1 grid gap-2 sm:grid-cols-3">
            <label
              v-for="a in EVENT_AUDIENCES"
              :key="a"
              class="flex cursor-pointer items-start gap-2 rounded-xl border p-3 text-sm transition"
              :class="audience === a ? 'border-brand-500 bg-brand-50 dark:border-brand-400 dark:bg-brand-950/40' : 'border-gray-200 dark:border-gray-800'"
            >
              <input v-model="audience" type="radio" name="audience" :value="a" class="mt-0.5 accent-brand-600" />
              <span>
                <span class="flex items-center gap-1 font-semibold"><component :is="AUDIENCE_ICONS[a]" class="h-4 w-4" aria-hidden="true" /> {{ t(`events.audiences.${a}`) }}</span>
                <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t(`events.audienceHints.${a}`) }}</span>
              </span>
            </label>
          </div>
        </fieldset>

        <div>
          <label for="event-capacity" class="label">{{ t("events.form.capacity") }}</label>
          <input id="event-capacity" v-model="capacity" type="number" min="1" max="100000" step="1" inputmode="numeric" class="input max-w-40" dir="ltr" />
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t("events.form.capacityHint") }}</p>
        </div>

        <p v-if="formError" class="text-sm font-medium text-red-600 dark:text-red-400" role="alert">{{ formError }}</p>

        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="router.back()">{{ t("feed.cancel") }}</button>
          <button type="submit" class="btn-gradient" :disabled="saving || uploading">
            {{ saving ? t("events.form.saving") : editingId ? t("events.form.save") : t("events.form.submit") }}
          </button>
        </div>
      </form>
    </div>
  </AppShell>
</template>
