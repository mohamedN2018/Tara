<script setup lang="ts">
// The navbar dropdown: the shared live list, with All / Unread chips, "New"
// and "Earlier" sections and "See previous notifications". The chips filter the
// rows already loaded (the Notifications page owns the store's server filter),
// and "See previous" pulls further pages from the server when they run out.
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import NotificationItem from "@/components/notifications/NotificationItem.vue";
import { DROPDOWN_PAGE, dropdownRows, splitByRecency } from "@/components/notifications/dropdownSections";
import { useNotificationActions } from "@/components/notifications/useNotificationActions";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { useNotificationStore } from "@/stores/notifications";
import { useToastStore } from "@/stores/toasts";
import type { Notification } from "@/types";

const props = withDefaults(defineProps<{ limit?: number }>(), { limit: DROPDOWN_PAGE });
const emit = defineEmits<{ navigate: [] }>();

const { t } = useI18n();
const store = useNotificationStore();
const actions = useNotificationActions();
const toasts = useToastStore();

const unreadOnly = ref(false);
const keep = ref<Set<string>>(new Set());
const shown = ref(props.limit);
const fetching = ref(false);
// Read once per opening: the dropdown is short-lived, so "New" need not tick.
const now = Date.now();

const matching = computed(() => dropdownRows(store.items, unreadOnly.value, keep.value));
const rows = computed(() => matching.value.slice(0, shown.value));
const sections = computed(() => {
  const { fresh, earlier } = splitByRecency(rows.value, now);
  return [
    { id: "new", label: t("socialShell.notifications.new"), rows: fresh },
    { id: "earlier", label: t("socialShell.notifications.earlier"), rows: earlier },
  ].filter((s) => s.rows.length);
});
const canSeePrevious = computed(() => matching.value.length > shown.value || store.hasMore);

/** Load further pages until `shown` rows match (at most three pages a click). */
async function fill() {
  if (fetching.value) return;
  fetching.value = true;
  try {
    for (let i = 0; i < 3 && matching.value.length < shown.value && store.hasMore; i++) await store.loadMore();
  } catch (e) {
    toasts.error(e);
  } finally {
    fetching.value = false;
  }
}

function seePrevious() {
  shown.value += DROPDOWN_PAGE;
  void fill();
}

function setUnread(value: boolean) {
  if (unreadOnly.value === value) return;
  unreadOnly.value = value;
  keep.value = new Set(value ? store.items.filter((n) => !n.read_at).map((n) => n.id) : []);
  shown.value = props.limit;
  if (value) void fill();
}

function opened(n: Notification) {
  actions.open(n);
  emit("navigate");
}

onMounted(() => {
  store.bind();
  void store.ensureLoaded();
});
</script>

<template>
  <div class="min-h-24">
    <div class="flex gap-2 px-2 pb-2" role="group" :aria-label="t('socialShell.notifications.filter')">
      <button
        v-for="f in ([false, true] as const)"
        :key="String(f)"
        type="button"
        class="chip"
        :class="unreadOnly === f ? 'chip-active' : ''"
        :aria-pressed="unreadOnly === f"
        :data-testid="`notif-dropdown-filter-${f ? 'unread' : 'all'}`"
        @click="setUnread(f)"
      >
        {{ t(`notifications.filters.${f ? "unread" : "all"}`) }}
      </button>
    </div>

    <LoadingSkeleton v-if="store.loading && !store.items.length" :rows="3" />
    <ErrorState v-else-if="store.error && !store.items.length" @retry="store.load" />
    <EmptyState v-else-if="!rows.length && !fetching">
      {{ unreadOnly ? t("notifications.emptyUnread") : t("notifications.empty") }}
    </EmptyState>
    <template v-else>
      <section
        v-for="s in sections"
        :key="s.id"
        :aria-labelledby="`notif-dropdown-${s.id}`"
        :data-testid="`notif-dropdown-section-${s.id}`"
      >
        <h4 :id="`notif-dropdown-${s.id}`" class="px-2 pb-1 pt-2 text-[15px] font-bold text-gray-900 dark:text-gray-100">
          {{ s.label }}
        </h4>
        <ul class="divide-y divide-gray-100 dark:divide-gray-800" aria-live="polite">
          <li v-for="n in s.rows" :key="n.id">
            <NotificationItem
              :notification="n"
              :busy="!!store.busy[n.id]"
              compact
              @open="opened"
              @read="actions.read"
              @dismiss="actions.dismiss"
              @action="actions.act"
              @turn-off="(n, done) => actions.turnOff(n).then(done)"
              @undo-turn-off="(n, done) => actions.undoTurnOff(n).then(done)"
            />
          </li>
        </ul>
      </section>
      <LoadingSkeleton v-if="fetching && !rows.length" :rows="2" />
    </template>

    <button
      v-if="canSeePrevious && (rows.length || store.hasMore)"
      type="button"
      class="btn-soft mt-2 w-full justify-center py-2 text-sm"
      :disabled="fetching || store.loadingMore"
      data-testid="notif-dropdown-see-previous"
      @click="seePrevious"
    >
      {{ fetching || store.loadingMore ? t("states.loading") : t("socialShell.notifications.seePrevious") }}
    </button>
  </div>
</template>
