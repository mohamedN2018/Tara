<script setup lang="ts">
import { BookOpenCheck, CheckCircle2, ChevronRight, ExternalLink, Flag, Inbox, LifeBuoy, Megaphone, MessageCircle, ShieldCheck } from "lucide-vue-next";
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import AppealDialog from "@/components/moderation/AppealDialog.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { relativeTime } from "@/lib/format";
import { useSafetyLabels } from "@/lib/safetyLabels";
import { moderationService, type MyCase, type MyReport, ownTargetLink } from "@/services/moderation";
import { chatService } from "@/services/chat";
import { notificationService } from "@/services/notification";
import { useDirectoryStore } from "@/stores/directory";
import { usePageDirectoryStore } from "@/stores/pageDirectory";
import { useToastStore } from "@/stores/toasts";
import type { Notification } from "@/types";

/**
 * The Support inbox: decisions about my content and account (with "Request
 * review"), where the reports I filed stand, and notices from the Tara team.
 * `?tab=status|reports|notices`; `?case=<id>` (from a notification) highlights
 * that decision. Everything here is the signed-in member's own, server-scoped.
 */
type Tab = "status" | "reports" | "notices";
const TABS: { id: Tab; icon: unknown }[] = [
  { id: "status", icon: ShieldCheck },
  { id: "reports", icon: Flag },
  { id: "notices", icon: Megaphone },
];

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const { targetLabel, reasonLabel } = useSafetyLabels();
const directory = useDirectoryStore();
const pageDirectory = usePageDirectoryStore();
const toasts = useToastStore();

// "Contact support": open (or reuse) my conversation with Tara Support.
const contacting = ref(false);
async function contactSupport() {
  if (contacting.value) return;
  contacting.value = true;
  try {
    const conversation = await chatService.openSupport();
    await router.push({ name: "messages", params: { id: conversation.id } });
  } catch (e) {
    toasts.error(e);
  } finally {
    contacting.value = false;
  }
}

const tab = computed<Tab>(() => {
  const q = String(route.query.tab ?? "");
  return (TABS.find((x) => x.id === q)?.id ?? "status") as Tab;
});
const focusCase = computed(() => (typeof route.query.case === "string" ? route.query.case : ""));

function select(id: Tab) {
  void router.replace({ query: { tab: id } });
}

interface Pager<T> {
  rows: T[];
  cursor: string | null;
  loading: boolean;
  error: boolean;
  more: boolean;
  loaded: boolean;
}
const blank = <T,>(): Pager<T> => ({ rows: [], cursor: null, loading: false, error: false, more: false, loaded: false });

const cases = ref<Pager<MyCase>>(blank());
const reports = ref<Pager<MyReport>>(blank());
const notices = ref<Pager<Notification>>(blank());

async function fill<T extends { id: string }>(
  state: Pager<T>,
  fetch: (cursor: string | null) => Promise<{ data: T[]; cursor: string | null }>,
  more = false,
) {
  if (more ? !state.cursor || state.more : state.loading) return;
  if (more) state.more = true;
  else {
    state.loading = true;
    state.error = false;
  }
  try {
    const page = await fetch(more ? state.cursor : null);
    const known = new Set(more ? state.rows.map((r) => r.id) : []);
    state.rows = more ? [...state.rows, ...page.data.filter((r) => !known.has(r.id))] : page.data;
    state.cursor = page.cursor;
    state.loaded = true;
  } catch {
    state.error = true;
  } finally {
    state.loading = false;
    state.more = false;
  }
}

const fetchCases = async (c: string | null) => {
  const p = await moderationService.myCases(c);
  return { data: p.data, cursor: p.page.next_cursor };
};
const fetchReports = async (c: string | null) => {
  const p = await moderationService.myReports(c);
  return { data: p.data, cursor: p.page.next_cursor };
};
const fetchNotices = async (c: string | null) => {
  // Filtered by kind on the server, so every page is full of notices.
  const p = await notificationService.list({ cursor: c, kind: "system.notice" });
  return { data: p.data ?? [], cursor: p.page?.next_cursor ?? null };
};

function load(id: Tab, force = false) {
  if (id === "status" && (force || !cases.value.loaded)) void fill(cases.value, fetchCases);
  if (id === "reports" && (force || !reports.value.loaded)) void fill(reports.value, fetchReports);
  if (id === "notices" && (force || !notices.value.loaded)) void fill(notices.value, fetchNotices);
}

watch(tab, (id) => load(id), { immediate: true });

// A notification's `?case=` scrolls to that decision once it is listed.
watch(
  () => [focusCase.value, cases.value.rows.length] as const,
  async ([id]) => {
    if (!id) return;
    await nextTick();
    document.getElementById(`case-${id}`)?.scrollIntoView?.({ block: "center" });
  },
);

const appealing = ref<MyCase | null>(null);
function appealed() {
  const c = appealing.value;
  appealing.value = null;
  if (!c) return;
  cases.value.rows = cases.value.rows.map((x) =>
    x.id === c.id ? { ...x, appeal_status: "open", appealed_at: new Date().toISOString(), can_appeal: false } : x,
  );
}

const reportState = (r: MyReport) =>
  r.state !== "resolved" ? "reviewing" : r.outcome === "actioned" ? "actioned" : "no_action";
const reportStateClass = (s: string) =>
  s === "reviewing"
    ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
    : s === "actioned"
      ? "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300"
      : "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200";
const appealClass = (s: string) =>
  s === "overturned"
    ? "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300"
    : s === "upheld"
      ? "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200"
      : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300";
</script>

<template>
  <AppShell :right="false">
    <div class="mx-auto max-w-5xl">
      <header class="mb-4 flex items-center gap-3">
        <span class="flex h-11 w-11 items-center justify-center rounded-full bg-brand-100 text-brand-700 dark:bg-brand-950 dark:text-brand-300">
          <LifeBuoy class="h-6 w-6" aria-hidden="true" />
        </span>
        <div>
          <h1 class="text-xl font-bold sm:text-2xl">{{ t("safety.support.title") }}</h1>
          <p class="text-sm text-gray-500 dark:text-gray-400">{{ t("safety.support.subtitle") }}</p>
        </div>
      </header>

      <div class="md:grid md:grid-cols-[17rem_minmax(0,1fr)] md:gap-5">
        <!-- Sections: a list on wide screens, chips on phones -->
        <aside class="mb-3 md:mb-0">
          <nav class="card p-2" :aria-label="t('safety.support.sections')" data-testid="support-nav">
            <ul class="flex gap-1 overflow-x-auto md:block md:space-y-0.5">
              <li v-for="x in TABS" :key="x.id" class="shrink-0">
                <button
                  type="button"
                  class="nav-item w-full whitespace-nowrap"
                  :class="tab === x.id ? 'nav-item-active' : ''"
                  :aria-current="tab === x.id ? 'page' : undefined"
                  :data-testid="`support-tab-${x.id}`"
                  @click="select(x.id)"
                >
                  <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-300">
                    <component :is="x.icon" class="h-5 w-5" aria-hidden="true" />
                  </span>
                  <span>{{ t(`safety.support.tabs.${x.id}`) }}</span>
                </button>
              </li>
            </ul>
          </nav>
          <RouterLink to="/legal/community-standards" class="card card-hover mt-3 hidden items-center gap-3 p-3 text-sm md:flex" data-testid="support-standards">
            <BookOpenCheck class="h-5 w-5 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
            <span class="min-w-0 flex-1 font-medium">{{ t("menu.items.communityStandards") }}</span>
            <ChevronRight class="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
          </RouterLink>
          <!-- Contact support: a conversation with Tara Support, answered by the moderation team -->
          <div class="card mt-3 p-3" data-testid="support-contact">
            <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("chatTeam.contactSupportHint") }}</p>
            <button type="button" class="btn-primary mt-2 w-full text-sm" :disabled="contacting" data-testid="support-contact-open" @click="contactSupport">
              <MessageCircle class="h-4 w-4" aria-hidden="true" /> {{ contacting ? t("chatTeam.opening") : t("chatTeam.contactSupport") }}
            </button>
          </div>
        </aside>

        <!-- Not a <main>: AppShell already renders the page's one main landmark. -->
        <div class="min-w-0">
          <!-- Account status: decisions about my content and account -->
          <section v-if="tab === 'status'" aria-labelledby="support-status" data-testid="support-status">
            <h2 id="support-status" class="sr-only">{{ t("safety.support.tabs.status") }}</h2>
            <LoadingSkeleton v-if="cases.loading" :rows="2" />
            <ErrorState v-else-if="cases.error" @retry="load('status', true)" />
            <div v-else-if="!cases.rows.length" class="card flex flex-col items-center gap-2 p-8 text-center" data-testid="support-status-clear">
              <CheckCircle2 class="h-10 w-10 text-green-600 dark:text-green-400" aria-hidden="true" />
              <p class="font-semibold">{{ t("safety.status.clearTitle") }}</p>
              <p class="max-w-md text-sm text-gray-500 dark:text-gray-400">{{ t("safety.status.clearBody") }}</p>
            </div>
            <ul v-else class="space-y-3">
              <li
                v-for="c in cases.rows"
                :id="`case-${c.id}`"
                :key="c.id"
                class="card p-4"
                :class="focusCase === c.id ? 'ring-2 ring-brand-500' : ''"
                data-testid="support-case"
              >
                <div class="flex items-start gap-3">
                  <span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-50 text-accent-700 dark:bg-accent-900/30 dark:text-accent-200">
                    <ShieldCheck class="h-5 w-5" aria-hidden="true" />
                  </span>
                  <div class="min-w-0 flex-1">
                    <p class="font-semibold">{{ t(`safety.status.headline.${c.decision}`, { target: targetLabel(c.target_type) }) }}</p>
                    <p class="text-xs text-gray-500 dark:text-gray-400">
                      <time v-if="c.decided_at" :datetime="c.decided_at">{{ relativeTime(c.decided_at) }}</time>
                    </p>
                    <p v-if="c.reason" class="mt-2 whitespace-pre-wrap break-words rounded-xl bg-gray-50 p-3 text-sm dark:bg-gray-950/60" dir="auto">
                      <span class="block text-xs font-semibold text-gray-500 dark:text-gray-400">{{ t("safety.status.reasonShared") }}</span>
                      {{ c.reason }}
                    </p>
                    <div class="mt-3 flex flex-wrap items-center gap-2">
                      <span v-if="c.appeal_status" class="rounded-full px-2 py-0.5 text-xs font-medium" :class="appealClass(c.appeal_status)" data-testid="support-appeal-status">
                        {{ t(`safety.status.appeal.${c.appeal_status}`) }}
                      </span>
                      <RouterLink
                        v-if="c.decision !== 'remove' && ownTargetLink(c.target_type, c.target_id)"
                        :to="ownTargetLink(c.target_type, c.target_id)!"
                        class="inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline dark:text-brand-300"
                      >
                        <ExternalLink class="h-4 w-4" aria-hidden="true" /> {{ t("safety.status.view") }}
                      </RouterLink>
                      <button v-if="c.can_appeal" type="button" class="btn-primary ms-auto text-sm" data-testid="support-request-review" @click="appealing = c">
                        {{ t("safety.status.requestReview") }}
                      </button>
                    </div>
                  </div>
                </div>
              </li>
            </ul>
            <div v-if="cases.cursor && !cases.loading" class="mt-3 flex justify-center">
              <button type="button" class="btn-ghost text-sm" :disabled="cases.more" @click="fill(cases, fetchCases, true)">{{ cases.more ? t("states.loading") : t("feed.loadMore") }}</button>
            </div>
          </section>

          <!-- Your reports -->
          <section v-else-if="tab === 'reports'" aria-labelledby="support-reports" data-testid="support-reports">
            <h2 id="support-reports" class="sr-only">{{ t("safety.support.tabs.reports") }}</h2>
            <LoadingSkeleton v-if="reports.loading" :rows="2" />
            <ErrorState v-else-if="reports.error" @retry="load('reports', true)" />
            <EmptyState v-else-if="!reports.rows.length">{{ t("safety.support.reportsEmpty") }}</EmptyState>
            <ul v-else class="card divide-y divide-gray-100 dark:divide-gray-800">
              <li v-for="r in reports.rows" :key="r.id" class="flex items-center gap-3 p-4" data-testid="support-report">
                <span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-300">
                  <Inbox class="h-5 w-5" aria-hidden="true" />
                </span>
                <div class="min-w-0 flex-1">
                  <p class="font-medium" data-testid="support-report-title">
                    <i18n-t v-if="r.target_type === 'user'" keypath="safety.support.reportedNamed" tag="span" scope="global">
                      <template #name><bdi>{{ directory.label(r.target_id) }}</bdi></template>
                    </i18n-t>
                    <i18n-t v-else-if="r.target_type === 'page'" keypath="safety.support.reportedPageNamed" tag="span" scope="global">
                      <template #name><bdi>{{ pageDirectory.label(r.target_id) }}</bdi></template>
                    </i18n-t>
                    <template v-else>{{ t("safety.support.reported", { target: targetLabel(r.target_type) }) }}</template>
                  </p>
                  <p class="text-xs text-gray-500 dark:text-gray-400">
                    {{ reasonLabel(r.reason) }} · <time :datetime="r.created_at">{{ relativeTime(r.created_at) }}</time>
                  </p>
                </div>
                <span class="shrink-0 rounded-full px-2 py-0.5 text-xs font-medium" :class="reportStateClass(reportState(r))">{{ t(`safety.support.reportState.${reportState(r)}`) }}</span>
              </li>
            </ul>
            <div v-if="reports.cursor && !reports.loading" class="mt-3 flex justify-center">
              <button type="button" class="btn-ghost text-sm" :disabled="reports.more" @click="fill(reports, fetchReports, true)">{{ reports.more ? t("states.loading") : t("feed.loadMore") }}</button>
            </div>
            <p class="mt-3 text-xs text-gray-500 dark:text-gray-400">{{ t("safety.support.reportsPrivacy") }}</p>
          </section>

          <!-- Notices from the Tara team -->
          <section v-else aria-labelledby="support-notices" data-testid="support-notices">
            <h2 id="support-notices" class="sr-only">{{ t("safety.support.tabs.notices") }}</h2>
            <LoadingSkeleton v-if="notices.loading" :rows="2" />
            <ErrorState v-else-if="notices.error" @retry="load('notices', true)" />
            <EmptyState v-else-if="!notices.rows.length">{{ t("safety.support.noticesEmpty") }}</EmptyState>
            <ul v-else class="space-y-3">
              <li v-for="n in notices.rows" :key="n.id" class="card flex gap-3 p-4" data-testid="support-notice">
                <span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-100 text-brand-700 dark:bg-brand-950 dark:text-brand-300">
                  <Megaphone class="h-5 w-5" aria-hidden="true" />
                </span>
                <div class="min-w-0 flex-1">
                  <p class="text-xs font-semibold text-gray-500 dark:text-gray-400">{{ t("safety.support.fromTeam") }} · <time :datetime="n.created_at">{{ relativeTime(n.created_at) }}</time></p>
                  <p class="mt-1 whitespace-pre-wrap break-words" dir="auto">{{ n.body }}</p>
                </div>
              </li>
            </ul>
            <div v-if="notices.cursor && !notices.loading" class="mt-3 flex justify-center">
              <button type="button" class="btn-ghost text-sm" :disabled="notices.more" @click="fill(notices, fetchNotices, true)">{{ notices.more ? t("states.loading") : t("feed.loadMore") }}</button>
            </div>
          </section>

          <RouterLink to="/legal/community-standards" class="card card-hover mt-4 flex items-center gap-3 p-3 text-sm md:hidden">
            <BookOpenCheck class="h-5 w-5 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
            <span class="min-w-0 flex-1 font-medium">{{ t("menu.items.communityStandards") }}</span>
            <ChevronRight class="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
          </RouterLink>
        </div>
      </div>
    </div>

    <AppealDialog v-if="appealing" :case-item="appealing" @close="appealing = null" @sent="appealed" />
  </AppShell>
</template>
