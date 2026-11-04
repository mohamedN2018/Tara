<script setup lang="ts">
import { ArrowLeft, Eye, LogOut, MailCheck, ShieldOff, ShieldPlus, X } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import AdminLayout from "@/components/admin/AdminLayout.vue";
import ConfirmDialog from "@/components/admin/ConfirmDialog.vue";
import { useAdminLabels } from "@/components/admin/labels";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { ROLES } from "@/lib/capabilities";
import { relativeTime } from "@/lib/format";
import { adminService, type AuditEntry } from "@/services/admin";
import { type PersonalData, type UserDetail, accountLabel, adminUsers, newIdempotencyKey } from "@/services/adminUsers";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";

type Tab = "overview" | "sessions" | "roles" | "activity";
type Dialog = "reveal" | "suspend" | "unsuspend" | "signOut" | "revoke" | null;

const { t, te, locale } = useI18n();
const route = useRoute();
const auth = useAuthStore();
const toasts = useToastStore();
const { roleLabel, actionLabel } = useAdminLabels();

const accountId = computed(() => String(route.params.id ?? ""));
const user = ref<UserDetail | null>(null);
const personal = ref<PersonalData | null>(null);
const loading = ref(true);
const error = ref(false);
const notFound = ref(false);

const tabs: Tab[] = ["overview", "sessions", "roles", "activity"];
const tab = ref<Tab>("overview");
const dialog = ref<Dialog>(null);
const busy = ref(false);
const roleToRevoke = ref("");
const roleToGrant = ref<string>(ROLES[1]);
// One key per opened suspend dialog: a double submit or a retry applies once.
const suspendKey = ref(newIdempotencyKey());

const activity = ref<AuditEntry[]>([]);
const activityCursor = ref<string | null>(null);
const activityLoaded = ref(false);
const activityError = ref(false);

const can = (cap: string) => auth.can(cap);
const isSelf = computed(() => auth.account?.id === accountId.value);
const name = computed(() => (user.value ? accountLabel({ ...user.value.profile, email_masked: user.value.email_masked }) : ""));
const suspended = computed(() => user.value?.status === "suspended");

const statusLabel = (status: string) => (te(`admin.users.status.${status}`) ? t(`admin.users.status.${status}`) : status);
const absolute = (iso: string | null) => {
  if (!iso) return t("admin.users.overview.never");
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : new Intl.DateTimeFormat(locale.value, { dateStyle: "medium", timeStyle: "short" }).format(d);
};
const listSeparator = computed(() => (locale.value === "ar" ? "، " : ", "));
const yesNo = (value: boolean) => t(value ? "admin.users.overview.yes" : "admin.users.overview.no");
const count = (value: number | null) => (value === null ? t("admin.users.overview.unavailable") : new Intl.NumberFormat(locale.value).format(value));
const detailText = (detail: Record<string, unknown>) =>
  Object.entries(detail ?? {})
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(", ");

async function load() {
  loading.value = true;
  error.value = false;
  notFound.value = false;
  try {
    user.value = await adminUsers.detail(accountId.value);
  } catch (e) {
    const status = (e as { response?: { status?: number } })?.response?.status;
    if (status === 404) notFound.value = true;
    else error.value = true;
  } finally {
    loading.value = false;
  }
}

async function loadActivity(more = false) {
  if (!can("admin.audit.view")) return;
  activityError.value = false;
  try {
    const page = await adminService.audit({ target_type: "account", target_id: accountId.value }, more ? activityCursor.value : null);
    const known = new Set(more ? activity.value.map((e) => e.id) : []);
    activity.value = more ? [...activity.value, ...page.data.filter((e) => !known.has(e.id))] : page.data;
    activityCursor.value = page.page.next_cursor;
    activityLoaded.value = true;
  } catch {
    activityError.value = true;
  }
}

function selectTab(next: Tab) {
  tab.value = next;
  if (next === "activity" && !activityLoaded.value) void loadActivity();
}

/** Arrow keys move between tabs; in RTL the arrows follow the reading direction. */
function onTabKey(e: KeyboardEvent) {
  const rtl = document.documentElement.dir === "rtl";
  const step = { ArrowRight: rtl ? -1 : 1, ArrowLeft: rtl ? 1 : -1 }[e.key as "ArrowRight" | "ArrowLeft"];
  let index = tabs.indexOf(tab.value);
  if (step) index = (index + step + tabs.length) % tabs.length;
  else if (e.key === "Home") index = 0;
  else if (e.key === "End") index = tabs.length - 1;
  else return;
  e.preventDefault();
  selectTab(tabs[index]);
  document.getElementById(`user-tab-${tabs[index]}`)?.focus();
}

function open(next: Dialog) {
  if (next === "suspend") suspendKey.value = newIdempotencyKey();
  dialog.value = next;
}

async function run(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  try {
    await action();
    dialog.value = null;
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

const reveal = ({ reason }: { reason: string }) =>
  run(async () => {
    personal.value = await adminUsers.reveal(accountId.value, reason);
    toasts.success(t("admin.users.reveal.revealed"));
    if (activityLoaded.value) void loadActivity();
  });

const suspend = ({ reason, until }: { reason: string; until: string | null }) =>
  run(async () => {
    await adminUsers.suspend(accountId.value, { reason, until }, suspendKey.value);
    toasts.success(t("admin.users.suspend.done"));
    personal.value = null; // its sessions are gone
    await load();
  });

const unsuspend = ({ reason }: { reason: string }) =>
  run(async () => {
    await adminUsers.unsuspend(accountId.value, reason);
    toasts.success(t("admin.users.unsuspend.done"));
    await load();
  });

const signOut = () =>
  run(async () => {
    const ended = await adminUsers.signOut(accountId.value);
    toasts.success(t("admin.users.signOut.done", { count: ended }, ended));
    personal.value = null;
    await load();
  });

async function resend() {
  if (busy.value) return;
  busy.value = true;
  try {
    await adminUsers.resendVerification(accountId.value);
    toasts.success(t("admin.users.resent"));
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

async function grantRole() {
  if (busy.value) return;
  busy.value = true;
  try {
    await adminService.grantRole(accountId.value, roleToGrant.value);
    await load();
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

function askRevoke(role: string) {
  roleToRevoke.value = role;
  open("revoke");
}

const revokeRole = () =>
  run(async () => {
    await adminService.revokeRole(accountId.value, roleToRevoke.value);
    await load();
  });

const removable = (role: string) =>
  !!user.value && !user.value.bridged_roles.includes(role) && !(role === "admin" && isSelf.value);

watch(accountId, () => {
  personal.value = null;
  activityLoaded.value = false;
  tab.value = "overview";
  void load();
});

onMounted(load);
</script>

<template>
  <AdminLayout :title="t('admin.sections.users')">

    <RouterLink to="/admin/users" class="btn-ghost mb-3 inline-flex items-center gap-1.5 text-sm">
      <ArrowLeft class="h-4 w-4 rtl:rotate-180" aria-hidden="true" /> {{ t("admin.users.back") }}
    </RouterLink>

    <LoadingSkeleton v-if="loading && !user" :rows="3" />
    <EmptyState v-else-if="notFound">{{ t("admin.users.notFound") }}</EmptyState>
    <ErrorState v-else-if="error && !user" @retry="load" />
    <template v-else-if="user">
      <section class="card mb-4 p-4" aria-labelledby="user-name" data-testid="user-header">
        <div class="flex flex-wrap items-center gap-2">
          <h2 id="user-name" class="text-lg font-bold" dir="auto">{{ name || t("admin.users.noName") }}</h2>
          <span
            class="rounded-full px-2 py-0.5 text-xs font-medium"
            :class="suspended ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300' : 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300'"
            data-testid="user-status"
          >
            {{ statusLabel(user.status) }}
          </span>
        </div>
        <p class="mt-1 text-xs text-gray-500 dark:text-gray-400" dir="ltr">{{ user.account_id }}</p>
        <p v-if="user.suspension" class="mt-2 text-sm text-red-700 dark:text-red-300" data-testid="user-suspension">
          {{ user.suspension.until ? t("admin.users.overview.suspendedUntil", { date: absolute(user.suspension.until) }) : t("admin.users.overview.suspendedIndefinitely") }}
          · <span dir="auto">{{ user.suspension.reason }}</span>
        </p>

        <div class="mt-3 flex flex-wrap gap-2" role="group" :aria-label="t('admin.users.actions.label')">
          <button v-if="can('admin.users.reveal') && !personal" type="button" class="btn-outline text-sm" @click="open('reveal')">
            <Eye class="h-4 w-4" aria-hidden="true" /> {{ t("admin.users.reveal.button") }}
          </button>
          <template v-if="!isSelf">
            <button v-if="can('admin.users.suspend') && !suspended" type="button" class="btn-outline text-sm" @click="open('suspend')">
              <ShieldOff class="h-4 w-4" aria-hidden="true" /> {{ t("admin.users.actions.suspend") }}
            </button>
            <button v-if="can('admin.users.suspend') && suspended" type="button" class="btn-outline text-sm" @click="open('unsuspend')">
              <ShieldPlus class="h-4 w-4" aria-hidden="true" /> {{ t("admin.users.actions.unsuspend") }}
            </button>
            <button v-if="can('admin.users.sign_out')" type="button" class="btn-outline text-sm" @click="open('signOut')">
              <LogOut class="h-4 w-4 rtl:rotate-180" aria-hidden="true" /> {{ t("admin.users.actions.signOut") }}
            </button>
          </template>
          <button
            v-if="can('admin.users.resend_verification') && !user.email_verified"
            type="button"
            class="btn-outline text-sm"
            :disabled="busy"
            @click="resend"
          >
            <MailCheck class="h-4 w-4" aria-hidden="true" /> {{ t("admin.users.actions.resend") }}
          </button>
        </div>
      </section>

      <div role="tablist" class="mb-3 flex flex-wrap gap-1 border-b border-gray-200 dark:border-gray-800" :aria-label="t('admin.users.tabs.label')" @keydown="onTabKey">
        <button
          v-for="key in tabs"
          :id="`user-tab-${key}`"
          :key="key"
          type="button"
          role="tab"
          :aria-selected="tab === key"
          :aria-controls="`user-panel-${key}`"
          :tabindex="tab === key ? 0 : -1"
          class="-mb-px border-b-2 px-3 py-2 text-sm font-medium"
          :class="tab === key ? 'border-brand-600 text-brand-700 dark:border-brand-400 dark:text-brand-300' : 'border-transparent text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white'"
          @click="selectTab(key)"
        >
          {{ t(`admin.users.tabs.${key}`) }}
        </button>
      </div>

      <!-- Overview -->
      <section v-show="tab === 'overview'" id="user-panel-overview" role="tabpanel" aria-labelledby="user-tab-overview" class="card p-4" data-testid="user-overview">
        <dl class="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <div>
            <dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("admin.users.overview.email") }}</dt>
            <dd>
              <span v-if="personal" dir="ltr" data-testid="revealed-email">{{ personal.email }}</span>
              <span v-else dir="ltr">{{ user.email_masked }}</span>
              · {{ user.email_verified ? t("admin.users.overview.verified") : t("admin.users.overview.notVerified") }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("admin.users.overview.phone") }}</dt>
            <dd>
              <template v-if="user.phone_verified">
                <span v-if="personal && personal.phone" dir="ltr" data-testid="revealed-phone">{{ personal.phone }}</span>
                <span v-else dir="ltr">{{ user.phone_masked }}</span>
                · {{ t("admin.users.overview.verified") }}
              </template>
              <template v-else>{{ t("admin.users.overview.noPhone") }}</template>
            </dd>
          </div>
          <div>
            <dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("admin.users.overview.created") }}</dt>
            <dd>{{ absolute(user.created_at) }}</dd>
          </div>
          <div>
            <dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("admin.users.overview.lastLogin") }}</dt>
            <dd>{{ absolute(user.last_login_at) }}</dd>
          </div>
          <div>
            <dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("admin.users.overview.sessions") }}</dt>
            <dd data-testid="active-sessions">{{ count(user.active_sessions) }}</dd>
          </div>
          <div>
            <dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("admin.users.overview.google") }}</dt>
            <dd>{{ yesNo(user.google_linked) }}</dd>
          </div>
          <div>
            <dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("admin.users.overview.roles") }}</dt>
            <dd>{{ user.roles.length ? user.roles.map((r) => roleLabel(r)).join(listSeparator) : t("admin.users.overview.noRoles") }}</dd>
          </div>
          <div>
            <dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("admin.users.overview.profile") }}</dt>
            <dd v-if="user.profile" dir="auto">
              {{ user.profile.display_name || "—" }} <span v-if="user.profile.handle" dir="ltr">@{{ user.profile.handle }}</span>
            </dd>
            <dd v-else>{{ t("admin.users.overview.noProfile") }}</dd>
          </div>
        </dl>
        <h3 class="mb-2 mt-4 text-sm font-semibold">{{ t("admin.users.overview.counts") }}</h3>
        <ul class="grid grid-cols-3 gap-2 text-center text-sm" data-testid="user-counts">
          <li class="rounded-lg border border-gray-100 p-2 dark:border-gray-800">
            <span class="block text-lg font-bold">{{ count(user.counts.posts) }}</span>{{ t("admin.users.overview.posts") }}
          </li>
          <li class="rounded-lg border border-gray-100 p-2 dark:border-gray-800">
            <span class="block text-lg font-bold">{{ count(user.counts.listings) }}</span>{{ t("admin.users.overview.listings") }}
          </li>
          <li class="rounded-lg border border-gray-100 p-2 dark:border-gray-800">
            <span class="block text-lg font-bold">{{ count(user.counts.open_cases) }}</span>{{ t("admin.users.overview.openCases") }}
          </li>
        </ul>
      </section>

      <!-- Sessions: personal data, only after a reveal -->
      <section v-show="tab === 'sessions'" id="user-panel-sessions" role="tabpanel" aria-labelledby="user-tab-sessions" class="card p-4" data-testid="user-sessions">
        <template v-if="personal">
          <EmptyState v-if="personal.sessions.length === 0">{{ t("admin.users.sessions.empty") }}</EmptyState>
          <ul v-else class="space-y-2">
            <li v-for="s in personal.sessions" :key="s.id" class="rounded-lg border border-gray-100 p-3 text-sm dark:border-gray-800">
              <span class="block font-medium" dir="ltr">{{ s.user_agent || s.platform }}</span>
              <span class="block text-xs text-gray-500 dark:text-gray-400">
                {{ t("admin.users.sessions.started") }} {{ absolute(s.created_at) }} · {{ t("admin.users.sessions.lastSeen") }} {{ absolute(s.last_seen_at) }}
                <template v-if="s.ip_region"> · {{ s.ip_region }}</template>
              </span>
            </li>
          </ul>
        </template>
        <div v-else class="flex flex-col items-start gap-2 text-sm">
          <p>{{ t("admin.users.reveal.needed") }}</p>
          <button v-if="can('admin.users.reveal')" type="button" class="btn-outline text-sm" @click="open('reveal')">
            <Eye class="h-4 w-4" aria-hidden="true" /> {{ t("admin.users.reveal.button") }}
          </button>
        </div>
      </section>

      <!-- Roles: the existing grant and revoke flow -->
      <section v-show="tab === 'roles'" id="user-panel-roles" role="tabpanel" aria-labelledby="user-tab-roles" class="card p-4" data-testid="user-roles">
        <ul v-if="user.roles.length" class="mb-3 flex flex-wrap gap-2">
          <li v-for="role in user.roles" :key="role" class="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-800">
            {{ roleLabel(role) }}
            <button
              v-if="can('admin.roles.manage') && removable(role)"
              type="button"
              class="rounded-full text-gray-500 hover:text-red-500 dark:text-gray-400"
              :aria-label="t('admin.users.roles.revoke', { role: roleLabel(role) })"
              @click="askRevoke(role)"
            >
              <X class="h-3 w-3" aria-hidden="true" />
            </button>
            <span v-else-if="user.bridged_roles.includes(role)" class="sr-only">{{ t("admin.users.roles.fromFlags") }}</span>
          </li>
        </ul>
        <p v-else class="mb-3 text-sm">{{ t("admin.users.overview.noRoles") }}</p>
        <form v-if="can('admin.roles.manage')" class="flex flex-wrap gap-2" @submit.prevent="grantRole">
          <select v-model="roleToGrant" class="input w-auto" :aria-label="t('admin.role')">
            <option v-for="r in ROLES" :key="r" :value="r">{{ roleLabel(r) }}</option>
          </select>
          <button type="submit" class="btn-primary shrink-0" :disabled="busy || user.roles.includes(roleToGrant)">{{ t("admin.grantRole") }}</button>
        </form>
        <p class="mt-2 text-xs text-gray-500 dark:text-gray-400">{{ t("admin.rolesHint") }}</p>
      </section>

      <!-- Activity: the audit log filtered by this account -->
      <section v-show="tab === 'activity'" id="user-panel-activity" role="tabpanel" aria-labelledby="user-tab-activity" class="card p-4" data-testid="user-activity">
        <p v-if="!can('admin.audit.view')" class="text-sm">{{ t("admin.users.activity.needsAudit") }}</p>
        <ErrorState v-else-if="activityError" @retry="loadActivity()" />
        <LoadingSkeleton v-else-if="!activityLoaded" :rows="2" />
        <EmptyState v-else-if="activity.length === 0">{{ t("admin.users.activity.empty") }}</EmptyState>
        <ul v-else class="space-y-2">
          <li v-for="e in activity" :key="e.id" class="rounded-lg border border-gray-100 p-3 text-sm dark:border-gray-800" :data-action="e.action">
            <span class="font-medium">{{ actionLabel(e.action) }}</span>
            · <time :datetime="e.occurred_at" :title="absolute(e.occurred_at)">{{ relativeTime(e.occurred_at) }}</time>
            <span class="block text-xs text-gray-500 dark:text-gray-400">
              <template v-if="e.actor_kind === 'system'">{{ t("admin.audit.system") }}</template>
              <span v-else dir="ltr">{{ e.actor_id }}</span>
              <template v-if="detailText(e.detail)"> · <span dir="ltr">{{ detailText(e.detail) }}</span></template>
            </span>
            <span v-if="e.reason" class="mt-1 block text-xs" dir="auto">{{ t("admin.users.reasonLabel") }}: {{ e.reason }}</span>
          </li>
        </ul>
        <div v-if="activityCursor && !activityError" class="mt-2 flex justify-center">
          <button type="button" class="btn-ghost text-sm" @click="loadActivity(true)">{{ t("feed.loadMore") }}</button>
        </div>
      </section>

      <ConfirmDialog
        :open="dialog === 'reveal'"
        :title="t('admin.users.reveal.title')"
        :hint="t('admin.users.reveal.hint')"
        :confirm-label="t('admin.users.reveal.confirm')"
        :danger="false"
        needs-reason
        :busy="busy"
        testid="reveal-dialog"
        @confirm="reveal"
        @cancel="dialog = null"
      />
      <ConfirmDialog
        :open="dialog === 'suspend'"
        :title="t('admin.users.suspend.title', { name })"
        :hint="t('admin.users.suspend.hint')"
        :confirm-label="t('admin.users.suspend.confirm')"
        needs-reason
        with-until
        :busy="busy"
        testid="suspend-dialog"
        @confirm="suspend"
        @cancel="dialog = null"
      />
      <ConfirmDialog
        :open="dialog === 'unsuspend'"
        :title="t('admin.users.unsuspend.title', { name })"
        :hint="t('admin.users.unsuspend.hint')"
        :confirm-label="t('admin.users.unsuspend.confirm')"
        :danger="false"
        needs-reason
        :busy="busy"
        testid="unsuspend-dialog"
        @confirm="unsuspend"
        @cancel="dialog = null"
      />
      <ConfirmDialog
        :open="dialog === 'signOut'"
        :title="t('admin.users.signOut.title', { name })"
        :hint="t('admin.users.signOut.hint')"
        :confirm-label="t('admin.users.signOut.confirm')"
        :busy="busy"
        testid="sign-out-dialog"
        @confirm="signOut"
        @cancel="dialog = null"
      />
      <ConfirmDialog
        :open="dialog === 'revoke'"
        :title="t('admin.users.roles.revokeTitle', { role: roleLabel(roleToRevoke) })"
        :hint="t('admin.users.roles.revokeHint')"
        :confirm-label="t('admin.users.roles.revokeConfirm')"
        :busy="busy"
        testid="revoke-dialog"
        @confirm="revokeRole"
        @cancel="dialog = null"
      />
    </template>
  </AdminLayout>
</template>
