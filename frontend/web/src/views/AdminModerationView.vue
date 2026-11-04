<script setup lang="ts">
import { Copy, ExternalLink, Flag, Gavel, Hand, ListChecks, Scale, ShieldAlert, UserCheck } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AdminLayout from "@/components/admin/AdminLayout.vue";
import ConfirmDialog from "@/components/admin/ConfirmDialog.vue";
import CaseDecisionDialog from "@/components/moderation/CaseDecisionDialog.vue";
import ReportList from "@/components/moderation/ReportList.vue";
import SafetyDialog from "@/components/moderation/SafetyDialog.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { relativeTime } from "@/lib/format";
import { useSafetyLabels } from "@/lib/safetyLabels";
import { adminService, type Appeal, type AppealStatus, type CaseQuery, type ModerationCase, targetLink } from "@/services/admin";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

/**
 * The moderator console: the case queue by state (open, in review, mine,
 * resolved), the raw reports stream and the appeals queue. `?tab=` keeps the
 * tab in the address, so the overview tiles and the back button land on it.
 * Every action is checked again on the server by capability.
 */
type CaseTab = "open" | "in_review" | "mine" | "resolved";
type Tab = CaseTab | "reports" | "appeals";

const { t, te } = useI18n();
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const toasts = useToastStore();
const directory = useDirectoryStore();

/** Whose content a case is about: the reported person, or the target's owner. */
function subjectName(c: { target_type: string; target_id: string; owner_id?: string | null }): string {
  if (c.target_type === "user") return directory.label(c.target_id);
  return c.owner_id ? directory.label(c.owner_id) : "";
}
async function copyId(id: string) {
  try {
    await navigator.clipboard.writeText(id);
    toasts.success(t("safety.mod.idCopied"));
  } catch (e) {
    toasts.error(e);
  }
}
const { targetLabel, stateLabel } = useSafetyLabels();

const canView = computed(() => auth.can("moderation.case.view"));
const canAct = computed(() => auth.can("moderation.case.act"));
const canViewAppeals = computed(() => auth.can("moderation.appeal.view"));
const canResolve = computed(() => auth.can("moderation.appeal.resolve"));
const me = computed(() => auth.account?.id ?? "");

const tabs = computed(() => {
  const list: { id: Tab; icon: unknown }[] = [];
  if (canView.value) {
    list.push(
      { id: "open", icon: ShieldAlert },
      { id: "in_review", icon: Hand },
      { id: "mine", icon: UserCheck },
      { id: "resolved", icon: ListChecks },
      { id: "reports", icon: Flag },
    );
  }
  if (canViewAppeals.value) list.push({ id: "appeals", icon: Scale });
  return list;
});

const tab = computed<Tab>(() => {
  const q = String(route.query.tab ?? "");
  return (tabs.value.find((x) => x.id === q)?.id ?? tabs.value[0]?.id ?? "open") as Tab;
});
const isCaseTab = computed(() => ["open", "in_review", "mine", "resolved"].includes(tab.value));

function select(id: Tab) {
  void router.replace({ query: { ...route.query, tab: id, status: undefined } });
}

// ---- cases --------------------------------------------------------------------

const cases = ref<ModerationCase[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(false);
const error = ref(false);
const loadingMore = ref(false);
const claiming = ref<string | null>(null);

function queryFor(id: CaseTab): CaseQuery {
  if (id === "mine") return { assigned: "me" };
  return { state: id };
}

let loadSeq = 0;
async function loadCases() {
  const seq = ++loadSeq;
  loading.value = true;
  error.value = false;
  try {
    const page = await adminService.cases(queryFor(tab.value as CaseTab));
    if (seq !== loadSeq) return;
    cases.value = page.data;
    cursor.value = page.page.next_cursor;
  } catch {
    if (seq === loadSeq) error.value = true;
  } finally {
    if (seq === loadSeq) loading.value = false;
  }
}

async function moreCases() {
  if (!cursor.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await adminService.cases(queryFor(tab.value as CaseTab), cursor.value);
    const known = new Set(cases.value.map((c) => c.id));
    cases.value = [...cases.value, ...page.data.filter((c) => !known.has(c.id))];
    cursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

async function claim(c: ModerationCase) {
  if (claiming.value) return;
  claiming.value = c.id;
  try {
    const updated = await adminService.assignCase(c.id);
    // Claimed: it leaves the Open tab and shows under In review / Mine.
    if (tab.value === "open") cases.value = cases.value.filter((x) => x.id !== c.id);
    else cases.value = cases.value.map((x) => (x.id === c.id ? { ...x, ...updated } : x));
    toasts.success(t("safety.mod.claimed"));
  } catch (e) {
    toasts.error(e, { conflict: "safety.mod.decision.conflict", not_found: "safety.mod.decision.gone" });
  } finally {
    claiming.value = null;
  }
}

const assigneeText = (c: ModerationCase) =>
  !c.assigned_to ? t("safety.mod.unassigned") : c.assigned_to === me.value ? t("safety.mod.assignedToYou") : t("safety.mod.assignedToOther");

const severityClass = (s: string | number) =>
  String(s) === "high" || String(s) === "critical"
    ? "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300"
    : "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200";

const stateClass = (s: string) =>
  s === "open"
    ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
    : s === "in_review"
      ? "bg-brand-100 text-brand-800 dark:bg-brand-950 dark:text-brand-300"
      : "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300";

// Case detail (its reports) and the decision dialog.
const detail = ref<ModerationCase | null>(null);
const deciding = ref<{ item: ModerationCase; initial: string } | null>(null);

function decided(c: ModerationCase) {
  deciding.value = null;
  detail.value = null;
  // Decided cases are resolved: they leave every tab but Resolved.
  if (tab.value === "resolved") void loadCases();
  else cases.value = cases.value.filter((x) => x.id !== c.id);
}

// ---- appeals -------------------------------------------------------------------

const appealStatuses: AppealStatus[] = ["open", "upheld", "overturned"];
const appealStatus = computed<AppealStatus>(() => {
  const s = String(route.query.status ?? "");
  return (appealStatuses as string[]).includes(s) ? (s as AppealStatus) : "open";
});
const appeals = ref<Appeal[]>([]);
const appealCursor = ref<string | null>(null);
const appealsLoading = ref(false);
const appealsError = ref(false);
const appealsMore = ref(false);
const resolving = ref<string | null>(null);
const overturning = ref<Appeal | null>(null);

async function loadAppeals() {
  appealsLoading.value = true;
  appealsError.value = false;
  try {
    const page = await adminService.appeals(appealStatus.value);
    appeals.value = page.data;
    appealCursor.value = page.page.next_cursor;
  } catch {
    appealsError.value = true;
  } finally {
    appealsLoading.value = false;
  }
}

async function moreAppeals() {
  if (!appealCursor.value || appealsMore.value) return;
  appealsMore.value = true;
  try {
    const page = await adminService.appeals(appealStatus.value, appealCursor.value);
    const known = new Set(appeals.value.map((a) => a.id));
    appeals.value = [...appeals.value, ...page.data.filter((a) => !known.has(a.id))];
    appealCursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    appealsMore.value = false;
  }
}

async function resolve(a: Appeal, status: Exclude<AppealStatus, "open">) {
  if (resolving.value) return;
  resolving.value = a.id;
  try {
    await adminService.resolveAppeal(a.id, status);
    appeals.value = appeals.value.filter((x) => x.id !== a.id);
    overturning.value = null;
    toasts.success(t(status === "overturned" ? "safety.mod.appeals.overturned" : "safety.mod.appeals.upheld"));
  } catch (e) {
    toasts.error(e, { conflict: "safety.mod.appeals.conflict" });
  } finally {
    resolving.value = null;
  }
}

function selectStatus(s: AppealStatus) {
  void router.replace({ query: { ...route.query, tab: "appeals", status: s } });
}

watch(
  [tab, appealStatus],
  () => {
    if (isCaseTab.value) void loadCases();
    else if (tab.value === "appeals") void loadAppeals();
  },
  { immediate: true },
);
</script>

<template>
  <AdminLayout :title="t('safety.console.sections.moderation')" :subtitle="t('safety.mod.subtitle')">
    <div role="tablist" class="mb-4 flex gap-1 overflow-x-auto border-b border-gray-200 dark:border-gray-800" :aria-label="t('safety.mod.tabsLabel')">
      <button
        v-for="x in tabs"
        :key="x.id"
        type="button"
        role="tab"
        :aria-selected="tab === x.id"
        class="-mb-px inline-flex shrink-0 items-center gap-1.5 border-b-[3px] px-3 py-2.5 text-sm font-semibold transition"
        :class="tab === x.id ? 'border-brand-600 text-brand-700 dark:border-brand-400 dark:text-brand-300' : 'border-transparent text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'"
        :data-testid="`mod-tab-${x.id}`"
        @click="select(x.id)"
      >
        <component :is="x.icon" class="h-4 w-4" aria-hidden="true" />
        {{ t(`safety.mod.tabs.${x.id}`) }}
      </button>
    </div>

    <!-- Case queue -->
    <section v-if="isCaseTab" role="tabpanel" data-testid="mod-cases">
      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error" @retry="loadCases" />
      <EmptyState v-else-if="!cases.length">{{ t(`safety.mod.empty.${tab}`) }}</EmptyState>
      <ul v-else class="space-y-3">
        <li v-for="c in cases" :key="c.id" class="card p-4" data-testid="mod-case">
          <div class="flex flex-wrap items-center gap-2">
            <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-300">
              <Gavel class="h-5 w-5" aria-hidden="true" />
            </span>
            <span class="min-w-0">
              <span class="block font-semibold" data-testid="mod-case-title">
                {{ targetLabel(c.target_type) }}<template v-if="subjectName(c)"> · <bdi>{{ c.target_type === "user" ? subjectName(c) : t("safety.mod.ownedBy", { name: subjectName(c) }) }}</bdi></template>
              </span>
              <span class="block text-xs text-gray-500 dark:text-gray-400">
                {{ t("admin.reportsCount", { count: c.report_count }, c.report_count) }} ·
                <time :datetime="c.created_at">{{ relativeTime(c.created_at) }}</time>
              </span>
            </span>
            <span class="ms-auto flex flex-wrap items-center gap-1.5 text-xs font-medium">
              <span class="rounded-full px-2 py-0.5" :class="severityClass(c.severity)">{{ t("safety.mod.severity", { level: te(`safety.mod.severityLevels.${c.severity}`) ? t(`safety.mod.severityLevels.${c.severity}`) : c.severity }) }}</span>
              <span class="rounded-full px-2 py-0.5" :class="stateClass(c.state)">{{ stateLabel(c.state) }}</span>
            </span>
          </div>

          <div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-600 dark:text-gray-300">
            <span class="inline-flex items-center gap-1" data-testid="mod-assignee"><UserCheck class="h-4 w-4" aria-hidden="true" />{{ assigneeText(c) }}</span>
            <RouterLink v-if="targetLink(c.target_type, c.target_id)" :to="targetLink(c.target_type, c.target_id)!" class="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline dark:text-brand-300">
              <ExternalLink class="h-4 w-4" aria-hidden="true" /> {{ t("safety.mod.viewContent") }}
            </RouterLink>
            <button v-else type="button" class="inline-flex items-center gap-1 text-xs text-gray-500 hover:underline dark:text-gray-400" :title="t('safety.mod.targetId')" data-testid="mod-copy-id" @click="copyId(c.target_id)">
              <Copy class="h-3.5 w-3.5" aria-hidden="true" /> {{ t("safety.mod.copyId") }}
            </button>
            <RouterLink v-if="c.target_type === 'user' && auth.can('admin.users.view')" :to="`/admin/users/${encodeURIComponent(c.target_id)}`" class="font-medium text-brand-700 hover:underline dark:text-brand-300">
              {{ t("safety.mod.accountConsole") }}
            </RouterLink>
          </div>

          <div class="mt-3 flex flex-wrap gap-2 border-t border-gray-100 pt-3 dark:border-gray-800">
            <button type="button" class="btn-soft text-sm" data-testid="mod-open-reports" @click="detail = c">
              <Flag class="h-4 w-4" aria-hidden="true" /> {{ t("safety.mod.reports.open", { count: c.report_count }, c.report_count) }}
            </button>
            <template v-if="canAct && c.state !== 'resolved'">
              <button
                v-if="c.state === 'open' && c.assigned_to !== me"
                type="button"
                class="btn-outline text-sm"
                :disabled="claiming === c.id"
                data-testid="mod-claim"
                @click="claim(c)"
              >
                <Hand class="h-4 w-4" aria-hidden="true" /> {{ t("safety.mod.claim") }}
              </button>
              <button type="button" class="btn-primary text-sm" data-testid="mod-decide" @click="deciding = { item: c, initial: '' }">
                <Gavel class="h-4 w-4" aria-hidden="true" /> {{ t("safety.mod.decide") }}
              </button>
              <button type="button" class="btn-ghost text-sm" data-testid="mod-dismiss" @click="deciding = { item: c, initial: 'dismiss' }">
                {{ t("safety.mod.actions.dismiss") }}
              </button>
            </template>
          </div>
        </li>
      </ul>
      <div v-if="cursor && !error && !loading" class="mt-3 flex justify-center">
        <button type="button" class="btn-ghost text-sm" :disabled="loadingMore" data-testid="mod-more" @click="moreCases">{{ loadingMore ? t("states.loading") : t("feed.loadMore") }}</button>
      </div>
    </section>

    <!-- Every report, newest first -->
    <section v-else-if="tab === 'reports'" role="tabpanel" class="card p-4" data-testid="mod-reports">
      <ReportList show-target />
    </section>

    <!-- Appeals -->
    <section v-else-if="tab === 'appeals'" role="tabpanel" data-testid="mod-appeals">
      <div class="mb-3 flex gap-2" role="group" :aria-label="t('safety.mod.appeals.filter')">
        <button
          v-for="s in appealStatuses"
          :key="s"
          type="button"
          class="chip"
          :class="appealStatus === s ? 'chip-active' : ''"
          :aria-pressed="appealStatus === s"
          :data-testid="`appeal-status-${s}`"
          @click="selectStatus(s)"
        >
          {{ t(`safety.appealStatus.${s}`) }}
        </button>
      </div>
      <LoadingSkeleton v-if="appealsLoading" :rows="2" />
      <ErrorState v-else-if="appealsError" @retry="loadAppeals" />
      <EmptyState v-else-if="!appeals.length">{{ t(`safety.mod.appeals.empty.${appealStatus}`) }}</EmptyState>
      <ul v-else class="space-y-3">
        <li v-for="a in appeals" :key="a.id" class="card p-4" data-testid="mod-appeal">
          <div class="flex flex-wrap items-center gap-2 text-sm">
            <Scale class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" />
            <span class="font-semibold">{{ t("safety.mod.appeals.about", { target: targetLabel(a.target_type) }) }}</span>
            <time class="ms-auto text-xs text-gray-500 dark:text-gray-400" :datetime="a.created_at">{{ relativeTime(a.created_at) }}</time>
          </div>
          <p class="mt-2 whitespace-pre-wrap break-words rounded-xl bg-gray-50 p-3 text-sm dark:bg-gray-950/60" dir="auto">{{ a.text }}</p>
          <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            <RouterLink :to="auth.can('admin.users.view') ? `/admin/users/${a.account_id}` : `/u/id/${a.account_id}`" class="font-medium text-brand-700 hover:underline dark:text-brand-300"><bdi>{{ directory.label(a.account_id) }}</bdi></RouterLink>
            <RouterLink v-if="targetLink(a.target_type, a.target_id)" :to="targetLink(a.target_type, a.target_id)!" class="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline dark:text-brand-300">
              <ExternalLink class="h-4 w-4" aria-hidden="true" /> {{ t("safety.mod.viewContent") }}
            </RouterLink>
            <span class="text-gray-500 dark:text-gray-400">{{ t("safety.mod.appeals.case") }} <span class="font-mono text-xs" dir="ltr">{{ a.case_id.slice(0, 8) }}</span></span>
            <span v-if="a.status !== 'open'" class="chip">{{ t(`safety.appealStatus.${a.status}`) }}</span>
          </div>
          <div v-if="canResolve && a.status === 'open'" class="mt-3 flex flex-wrap justify-end gap-2 border-t border-gray-100 pt-3 dark:border-gray-800">
            <button type="button" class="btn-soft text-sm" :disabled="resolving === a.id" data-testid="appeal-uphold" @click="resolve(a, 'upheld')">{{ t("admin.appeals.uphold") }}</button>
            <button type="button" class="btn-primary text-sm" :disabled="resolving === a.id" data-testid="appeal-overturn" @click="overturning = a">{{ t("admin.appeals.overturn") }}</button>
          </div>
        </li>
      </ul>
      <div v-if="appealCursor && !appealsError && !appealsLoading" class="mt-3 flex justify-center">
        <button type="button" class="btn-ghost text-sm" :disabled="appealsMore" @click="moreAppeals">{{ appealsMore ? t("states.loading") : t("feed.loadMore") }}</button>
      </div>
    </section>

    <EmptyState v-if="!tabs.length">{{ t("safety.console.overview.nothing") }}</EmptyState>

    <!-- Case detail: who reported it and why -->
    <SafetyDialog v-if="detail" :title="t('safety.mod.reports.title', { target: targetLabel(detail.target_type) })" wide testid="case-detail" @close="detail = null">
      <p v-if="subjectName(detail)" class="mb-2 text-sm font-semibold" data-testid="case-detail-subject">
        <bdi>{{ detail.target_type === "user" ? t("safety.mod.profileOf", { name: subjectName(detail) }) : t("safety.mod.ownedBy", { name: subjectName(detail) }) }}</bdi>
      </p>
      <dl class="mb-3 grid grid-cols-2 gap-2 text-sm">
        <div><dt class="text-gray-500 dark:text-gray-400">{{ t("safety.mod.stateLabel") }}</dt><dd class="font-medium">{{ stateLabel(detail.state) }}</dd></div>
        <div><dt class="text-gray-500 dark:text-gray-400">{{ t("safety.mod.assigneeLabel") }}</dt><dd class="font-medium">{{ assigneeText(detail) }}</dd></div>
      </dl>
      <ReportList :case-id="detail.id" />
      <template v-if="canAct && detail.state !== 'resolved'" #footer>
        <button type="button" class="btn-ghost" @click="deciding = { item: detail!, initial: 'dismiss' }">{{ t("safety.mod.actions.dismiss") }}</button>
        <button type="button" class="btn-primary" data-testid="detail-decide" @click="deciding = { item: detail!, initial: '' }">{{ t("safety.mod.decide") }}</button>
      </template>
    </SafetyDialog>

    <CaseDecisionDialog v-if="deciding" :case-item="deciding.item" :initial="deciding.initial" @close="deciding = null" @done="decided(deciding!.item)" />

    <ConfirmDialog
      :open="!!overturning"
      :title="t('safety.mod.appeals.overturnTitle')"
      :hint="overturning ? t('safety.mod.appeals.overturnHint', { target: targetLabel(overturning.target_type) }) : ''"
      :confirm-label="t('admin.appeals.overturn')"
      :busy="!!resolving"
      testid="overturn-confirm"
      @confirm="overturning && resolve(overturning, 'overturned')"
      @cancel="overturning = null"
    />
  </AdminLayout>
</template>
