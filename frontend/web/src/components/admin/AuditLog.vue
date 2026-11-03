<script setup lang="ts">
import { ClipboardList, Download } from "lucide-vue-next";
import { onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { relativeTime } from "@/lib/format";
import { AUDIT_ACTIONS, adminService, type AuditEntry, type AuditFilters } from "@/services/admin";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";

import { useAdminLabels } from "./labels";

const { t, locale } = useI18n();
const auth = useAuthStore();
const toasts = useToastStore();
const { actionLabel } = useAdminLabels();

// What the form shows, and what the list was last loaded with.
const form = reactive({ actor: "", action: "", target_type: "", target_id: "", since: "", until: "" });
const applied = ref<AuditFilters>({});

const entries = ref<AuditEntry[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
const exporting = ref(false);

/** A date input is local; the API takes ISO datetimes. `until` covers the whole day. */
function dayBound(day: string, end: boolean): string {
  if (!day) return "";
  const d = new Date(`${day}T00:00:00`);
  if (Number.isNaN(d.getTime())) return "";
  if (end) d.setDate(d.getDate() + 1);
  return d.toISOString();
}

function filtersFromForm(): AuditFilters {
  return {
    actor: form.actor,
    action: form.action,
    target_type: form.target_type,
    target_id: form.target_id,
    since: dayBound(form.since, false),
    until: dayBound(form.until, true),
  };
}

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const page = await adminService.audit(applied.value);
    entries.value = page.data;
    cursor.value = page.page.next_cursor;
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

function apply() {
  applied.value = filtersFromForm();
  void load();
}

function clear() {
  Object.assign(form, { actor: "", action: "", target_type: "", target_id: "", since: "", until: "" });
  apply();
}

async function more() {
  if (!cursor.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await adminService.audit(applied.value, cursor.value);
    const known = new Set(entries.value.map((e) => e.id));
    entries.value = [...entries.value, ...page.data.filter((e) => !known.has(e.id))];
    cursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

async function download() {
  if (exporting.value) return;
  exporting.value = true;
  try {
    await adminService.exportAudit(applied.value);
  } catch (e) {
    toasts.error(e);
  } finally {
    exporting.value = false;
  }
}

const absolute = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : new Intl.DateTimeFormat(locale.value, { dateStyle: "medium", timeStyle: "short" }).format(d);
};

const detailText = (detail: Record<string, unknown>) =>
  Object.entries(detail ?? {})
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(", ");

onMounted(load);
</script>

<template>
  <section aria-labelledby="audit-title">
    <h2 id="audit-title" class="mb-3 flex items-center gap-2 font-semibold">
      <ClipboardList class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("admin.audit.title") }}
      <button
        v-if="auth.can('admin.audit.export')"
        type="button"
        class="btn-ghost ms-auto inline-flex items-center gap-1.5 text-sm"
        :disabled="exporting"
        @click="download"
      >
        <Download class="h-4 w-4" aria-hidden="true" /> {{ exporting ? t("admin.audit.exporting") : t("admin.audit.export") }}
      </button>
    </h2>

    <form class="card mb-4 grid gap-3 p-3 sm:grid-cols-2 lg:grid-cols-3" :aria-label="t('admin.audit.filters')" @submit.prevent="apply">
      <label class="flex flex-col gap-1 text-sm">
        {{ t("admin.audit.actor") }}
        <input v-model="form.actor" class="input" dir="ltr" maxlength="64" :placeholder="t('admin.audit.actorHint')" />
      </label>
      <label class="flex flex-col gap-1 text-sm">
        {{ t("admin.audit.action") }}
        <select v-model="form.action" class="input">
          <option value="">{{ t("admin.audit.anyAction") }}</option>
          <option v-for="a in AUDIT_ACTIONS" :key="a" :value="a">{{ actionLabel(a) }}</option>
        </select>
      </label>
      <label class="flex flex-col gap-1 text-sm">
        {{ t("admin.audit.targetType") }}
        <input v-model="form.target_type" class="input" dir="ltr" maxlength="40" />
      </label>
      <label class="flex flex-col gap-1 text-sm">
        {{ t("admin.audit.targetId") }}
        <input v-model="form.target_id" class="input" dir="ltr" maxlength="64" />
      </label>
      <label class="flex flex-col gap-1 text-sm">
        {{ t("admin.audit.since") }}
        <input v-model="form.since" class="input" type="date" dir="ltr" />
      </label>
      <label class="flex flex-col gap-1 text-sm">
        {{ t("admin.audit.until") }}
        <input v-model="form.until" class="input" type="date" dir="ltr" />
      </label>
      <div class="flex gap-2 sm:col-span-2 lg:col-span-3">
        <button type="submit" class="btn-primary text-sm">{{ t("admin.audit.apply") }}</button>
        <button type="button" class="btn-ghost text-sm" @click="clear">{{ t("admin.audit.clear") }}</button>
      </div>
    </form>

    <LoadingSkeleton v-if="loading" :rows="3" />
    <ErrorState v-else-if="error" @retry="load" />
    <EmptyState v-else-if="entries.length === 0">{{ t("admin.audit.empty") }}</EmptyState>
    <div v-else class="card overflow-x-auto">
      <table class="w-full border-collapse text-sm" data-testid="audit-entries">
        <thead>
          <tr class="text-start text-xs text-gray-500 dark:text-gray-400">
            <th scope="col" class="px-3 py-2 text-start font-semibold">{{ t("admin.audit.when") }}</th>
            <th scope="col" class="px-3 py-2 text-start font-semibold">{{ t("admin.audit.who") }}</th>
            <th scope="col" class="px-3 py-2 text-start font-semibold">{{ t("admin.audit.what") }}</th>
            <th scope="col" class="px-3 py-2 text-start font-semibold">{{ t("admin.audit.target") }}</th>
            <th scope="col" class="px-3 py-2 text-start font-semibold">{{ t("admin.audit.requestId") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in entries" :key="e.id" class="border-t border-gray-100 align-top dark:border-gray-800" :data-action="e.action">
            <td class="whitespace-nowrap px-3 py-2">
              <time :datetime="e.occurred_at" :title="absolute(e.occurred_at)">{{ relativeTime(e.occurred_at) }}</time>
              <span class="block text-xs text-gray-500 dark:text-gray-400">{{ absolute(e.occurred_at) }}</span>
            </td>
            <td class="px-3 py-2">
              <span v-if="e.actor_kind === 'system'">{{ t("admin.audit.system") }}<span v-if="e.actor_name" class="block text-xs text-gray-500 dark:text-gray-400" dir="ltr">{{ e.actor_name }}</span></span>
              <span v-else class="block max-w-[12rem] truncate text-xs" dir="ltr" :title="e.actor_id ?? ''">{{ e.actor_id }}</span>
            </td>
            <td class="px-3 py-2">
              {{ actionLabel(e.action) }}
              <span v-if="detailText(e.detail)" class="block break-all text-xs text-gray-500 dark:text-gray-400" dir="ltr">{{ detailText(e.detail) }}</span>
              <span v-if="e.reason" class="block break-words text-xs" dir="auto" data-testid="audit-reason">{{ t("admin.users.reasonLabel") }}: {{ e.reason }}</span>
            </td>
            <td class="px-3 py-2">
              <span class="block text-xs" dir="ltr">{{ e.target_type }}</span>
              <span class="block max-w-[12rem] truncate text-xs text-gray-500 dark:text-gray-400" dir="ltr" :title="e.target_id">{{ e.target_id }}</span>
            </td>
            <td class="px-3 py-2">
              <span class="block max-w-[10rem] truncate text-xs text-gray-500 dark:text-gray-400" dir="ltr" :title="e.request_id" data-testid="request-id">{{ e.request_id }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="cursor && !error && !loading" class="mt-2 flex justify-center">
      <button type="button" class="btn-ghost text-sm" :disabled="loadingMore" @click="more">
        {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
      </button>
    </div>
  </section>
</template>
