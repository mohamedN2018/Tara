<script setup lang="ts">
import { CalendarPlus, Search } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import EventCard from "@/components/events/EventCard.vue";
import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { EVENT_SCOPES, type EventScope, eventsService, type TaraEvent } from "@/services/events";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const toasts = useToastStore();

const isScope = (v: unknown): v is EventScope => typeof v === "string" && (EVENT_SCOPES as string[]).includes(v);
const tab = ref<EventScope>(isScope(route.query.tab) ? route.query.tab : "upcoming");
const query = ref("");
const items = ref<TaraEvent[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
let generation = 0;

async function load() {
  const mine = ++generation;
  loading.value = true;
  error.value = false;
  try {
    const page = await eventsService.list(tab.value, null, query.value.trim());
    if (mine !== generation) return;
    items.value = page.data;
    cursor.value = page.page.next_cursor;
  } catch {
    if (mine === generation) error.value = true;
  } finally {
    if (mine === generation) loading.value = false;
  }
}

async function loadMore() {
  if (!cursor.value || loadingMore.value) return;
  loadingMore.value = true;
  const mine = generation;
  try {
    const page = await eventsService.list(tab.value, cursor.value, query.value.trim());
    if (mine !== generation) return;
    items.value = [...items.value, ...page.data];
    cursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

function pick(scope: EventScope) {
  if (tab.value === scope) return;
  tab.value = scope;
  router.replace({ query: { ...route.query, tab: scope === "upcoming" ? undefined : scope } });
}

function focusTab(e: KeyboardEvent, index: number) {
  // Arrow keys move along the tab list; the visual order flips in RTL.
  const rtl = document.documentElement.dir === "rtl";
  const step = { ArrowRight: rtl ? -1 : 1, ArrowLeft: rtl ? 1 : -1 }[e.key];
  if (!step) return;
  e.preventDefault();
  const next = (index + step + EVENT_SCOPES.length) % EVENT_SCOPES.length;
  pick(EVENT_SCOPES[next]);
  (document.getElementById(`events-tab-${EVENT_SCOPES[next]}`) as HTMLElement | null)?.focus();
}

let searchTimer: number | undefined;
watch(query, () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(load, 300);
});
watch(tab, load);
onMounted(load);
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[720px] space-y-4">
      <div class="flex flex-wrap items-center gap-3 px-1">
        <h1 class="text-xl font-bold">{{ t("events.title") }}</h1>
        <RouterLink to="/events/new" class="btn-gradient ms-auto">
          <CalendarPlus class="h-4 w-4" aria-hidden="true" /> {{ t("events.create") }}
        </RouterLink>
      </div>

      <div class="flex gap-1 overflow-x-auto rounded-xl bg-gray-100 p-1 text-sm dark:bg-gray-800" role="tablist" :aria-label="t('events.title')">
        <button
          v-for="(scope, i) in EVENT_SCOPES"
          :id="`events-tab-${scope}`"
          :key="scope"
          role="tab"
          :aria-selected="tab === scope"
          :tabindex="tab === scope ? 0 : -1"
          aria-controls="events-panel"
          class="flex-1 whitespace-nowrap rounded-lg px-3 py-1.5 font-medium transition"
          :class="tab === scope ? 'bg-white text-brand-600 shadow-sm dark:bg-gray-900 dark:text-brand-300' : 'text-gray-500 dark:text-gray-400'"
          @click="pick(scope)"
          @keydown="focusTab($event, i)"
        >
          {{ t(`events.tabs.${scope}`) }}
        </button>
      </div>

      <label class="relative block">
        <span class="sr-only">{{ t("events.search") }}</span>
        <Search class="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden="true" />
        <input v-model="query" type="search" class="input ps-9" :placeholder="t('events.search')" dir="auto" maxlength="100" />
      </label>

      <div id="events-panel" role="tabpanel" :aria-labelledby="`events-tab-${tab}`">
        <LoadingSkeleton v-if="loading" :rows="3" />
        <ErrorState v-else-if="error" @retry="load" />
        <EmptyState v-else-if="items.length === 0">{{ t(`events.empty.${tab}`) }}</EmptyState>
        <div v-else class="grid gap-3 sm:grid-cols-2">
          <EventCard v-for="e in items" :key="e.id" :event="e" />
        </div>
        <button v-if="!loading && !error && cursor" class="btn-ghost mx-auto mt-3 block" :disabled="loadingMore" @click="loadMore">
          {{ loadingMore ? t("states.loading") : t("states.loadMore") }}
        </button>
      </div>
    </div>
  </AppShell>
</template>
