<script setup lang="ts">
// Feed and content preferences: the people you see more of (favorites) or less
// of (muted, restricted, blocked, snoozed). Graph and feed own these lists and
// enforce them; this only lists them and removes entries.
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { RouterLink, useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { blockedAvatar, blockedLabel, loadBlockedCards } from "@/lib/blockedCards";
import { type PrefKind, useRelationshipPrefs } from "@/lib/useRelationshipPrefs";
import { feedService, type Snooze } from "@/services/feed";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

type Tab = PrefKind | "snoozed";
const TABS: Tab[] = ["favorites", "mutes", "restricted", "blocks", "snoozed"];

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const prefs = useRelationshipPrefs();
const directory = useDirectoryStore();
const toasts = useToastStore();

const fromHash = (hash: string): Tab => {
  const h = hash.replace("#", "") as Tab;
  return TABS.includes(h) ? h : "favorites";
};
const tab = ref<Tab>(fromHash(route.hash));
const listFailed = ref(false);
const snoozes = ref<Snooze[] | null>(null);
const snoozeCursor = ref<string | null>(null);
const busy = ref<string | null>(null);

async function loadTab(which: Tab) {
  listFailed.value = false;
  if (which === "snoozed") {
    try {
      const page = await feedService.snoozes();
      snoozes.value = page.data;
      snoozeCursor.value = page.page.has_more ? page.page.next_cursor : null;
    } catch {
      listFailed.value = true;
    }
    return;
  }
  await prefs.ensure([which]);
  if (!prefs.loaded(which)) listFailed.value = true;
  // Blocked people are hidden from the shared directory: name them separately.
  else if (which === "blocks") await loadBlockedCards(prefs.list("blocks"));
}

const nameFor = (id: string) => (tab.value === "blocks" ? blockedLabel(id) : directory.label(id));
const avatarFor = (id: string) => (tab.value === "blocks" ? blockedAvatar(id) : directory.avatarOf(id));

async function moreSnoozes() {
  if (!snoozeCursor.value) return;
  try {
    const page = await feedService.snoozes(snoozeCursor.value);
    snoozes.value = [...(snoozes.value ?? []), ...page.data];
    snoozeCursor.value = page.page.has_more ? page.page.next_cursor : null;
  } catch (e) {
    toasts.error(e);
  }
}

function select(next: Tab) {
  tab.value = next;
  void router.replace({ hash: `#${next}` });
}

const ids = (which: Tab): string[] =>
  which === "snoozed" ? (snoozes.value ?? []).map((s) => s.author_id) : prefs.list(which);

const loaded = (which: Tab) => (which === "snoozed" ? snoozes.value !== null : prefs.loaded(which));

async function remove(id: string) {
  if (busy.value) return;
  busy.value = id;
  try {
    if (tab.value === "snoozed") {
      await feedService.unsnooze(id);
      snoozes.value = (snoozes.value ?? []).filter((s) => s.author_id !== id);
    } else {
      await prefs.set(tab.value, id, false);
    }
    toasts.success(t("settingsCenter.content.removed"));
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = null;
  }
}

const until = (id: string) => {
  const s = snoozes.value?.find((x) => x.author_id === id);
  return s ? new Intl.DateTimeFormat(locale.value, { dateStyle: "medium" }).format(new Date(s.until)) : "";
};

function onKey(e: KeyboardEvent) {
  const i = TABS.indexOf(tab.value);
  const rtl = document.documentElement.dir === "rtl";
  const step = e.key === "ArrowRight" ? (rtl ? -1 : 1) : e.key === "ArrowLeft" ? (rtl ? 1 : -1) : 0;
  if (!step) return;
  e.preventDefault();
  const next = TABS[(i + step + TABS.length) % TABS.length];
  select(next);
  void Promise.resolve().then(() => document.getElementById(`content-tab-${next}`)?.focus());
}

watch(tab, (next) => void loadTab(next));
watch(
  () => route.hash,
  (hash) => {
    const next = fromHash(hash);
    if (next !== tab.value) tab.value = next;
  },
);
onMounted(() => void loadTab(tab.value));
</script>

<template>
  <section class="card mb-4 p-4" data-testid="content-preferences">
    <p class="mb-3 text-sm text-gray-600 dark:text-gray-300">{{ t("settingsCenter.content.lead") }}</p>

    <div
      role="tablist"
      :aria-label="t('settingsCenter.content.tabs')"
      class="mb-3 flex flex-wrap gap-x-1 border-b border-gray-200 sm:flex-nowrap sm:overflow-x-auto dark:border-gray-800"
      @keydown="onKey"
    >
      <button
        v-for="tb in TABS"
        :id="`content-tab-${tb}`"
        :key="tb"
        type="button"
        role="tab"
        :aria-selected="tab === tb"
        :aria-controls="`content-panel-${tb}`"
        :tabindex="tab === tb ? 0 : -1"
        class="-mb-px shrink-0 border-b-[3px] px-3 py-2 text-sm font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
        :class="tab === tb ? 'border-brand-600 text-brand-700 dark:border-brand-400 dark:text-brand-300' : 'border-transparent text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800'"
        :data-testid="`content-tab-${tb}`"
        @click="select(tb)"
      >
        {{ t(`settingsCenter.content.${tb}`) }}
      </button>
    </div>

    <div :id="`content-panel-${tab}`" role="tabpanel" :aria-labelledby="`content-tab-${tab}`" tabindex="0" class="focus:outline-none">
      <p class="mb-3 text-xs text-gray-500 dark:text-gray-400">{{ t(`settingsCenter.content.hints.${tab}`) }}</p>
      <p v-if="listFailed" class="flex items-center justify-between gap-2 text-sm text-gray-500 dark:text-gray-400">
        {{ t("settingsCenter.content.failed") }}
        <button type="button" class="btn-ghost text-sm" @click="loadTab(tab)">{{ t("states.retry") }}</button>
      </p>
      <p v-else-if="!loaded(tab)" class="text-sm text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
      <p v-else-if="!ids(tab).length" class="py-4 text-center text-sm text-gray-500 dark:text-gray-400" data-testid="content-empty">
        {{ t(`settingsCenter.content.empty.${tab}`) }}
      </p>
      <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800">
        <li v-for="id in ids(tab)" :key="id" class="flex items-center gap-3 py-2" data-testid="content-row">
          <!-- A blocked person's profile is a 404 for the blocker: no link. -->
          <component
            :is="tab === 'blocks' ? 'span' : RouterLink"
            v-bind="tab === 'blocks' ? {} : { to: { name: 'profile-by-id', params: { id } } }"
            class="flex min-w-0 flex-1 items-center gap-3"
            :class="tab === 'blocks' ? '' : 'hover:underline'"
          >
            <UserAvatar :name="nameFor(id)" :media-id="avatarFor(id)" :size="40" />
            <span class="min-w-0">
              <span class="block truncate text-sm font-semibold" dir="auto" data-testid="content-row-name">{{ nameFor(id) }}</span>
              <span v-if="tab === 'snoozed'" class="block text-xs text-gray-500 dark:text-gray-400">
                {{ t("settingsCenter.content.until", { date: until(id) }) }}
              </span>
            </span>
          </component>
          <button type="button" class="btn-soft shrink-0 text-sm" :disabled="busy === id" @click="remove(id)">
            {{ t(`settingsCenter.content.remove.${tab}`) }}
          </button>
        </li>
      </ul>
      <button v-if="tab === 'snoozed' && snoozeCursor" type="button" class="btn-ghost mt-2 w-full text-sm" @click="moreSnoozes">
        {{ t("settingsCenter.activity.more") }}
      </button>
    </div>
  </section>
</template>
