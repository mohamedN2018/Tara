<script setup lang="ts">
import { Megaphone, Search, X } from "lucide-vue-next";
import { computed, onMounted, ref, useId } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import AdminLayout from "@/components/admin/AdminLayout.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { relativeTime } from "@/lib/format";
import { adminService, NOTICE_MAX_BODY, NOTICE_MAX_RECIPIENTS, type SystemNotice } from "@/services/admin";
import { adminUsers, type UserRow } from "@/services/adminUsers";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";

/**
 * Announcements: an administrative notice to some accounts (1-50). Each
 * recipient gets it as a notification from the Tara team; this page keeps the
 * history. `?to=<account id>` (from a user's page) starts with that account.
 */
const { t } = useI18n();
const route = useRoute();
const auth = useAuthStore();
const toasts = useToastStore();
const uid = useId();

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const canSearch = computed(() => auth.can("admin.users.view"));

interface Recipient {
  id: string;
  label: string;
}

const recipients = ref<Recipient[]>([]);
const body = ref("");
const sending = ref(false);
const query = ref("");
const results = ref<UserRow[]>([]);
const searching = ref(false);
const searchError = ref("");
const pasted = ref("");

const sent = ref<SystemNotice[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const error = ref(false);
const loadingMore = ref(false);

const remaining = computed(() => NOTICE_MAX_BODY - body.value.length);
const canSend = computed(
  () => !sending.value && recipients.value.length > 0 && recipients.value.length <= NOTICE_MAX_RECIPIENTS && body.value.trim().length > 0,
);

function add(id: string, label: string) {
  const value = id.toLowerCase();
  if (recipients.value.some((r) => r.id === value)) return;
  if (recipients.value.length >= NOTICE_MAX_RECIPIENTS) {
    toasts.error(t("safety.console.notices.tooMany", { max: NOTICE_MAX_RECIPIENTS }));
    return;
  }
  recipients.value = [...recipients.value, { id: value, label }];
}

function remove(id: string) {
  recipients.value = recipients.value.filter((r) => r.id !== id);
}

function addPasted() {
  const value = pasted.value.trim();
  if (!UUID.test(value)) {
    toasts.error(t("safety.console.notices.badId"));
    return;
  }
  add(value, value);
  pasted.value = "";
}

async function search() {
  const q = query.value.trim();
  if (!q || searching.value) return;
  searching.value = true;
  searchError.value = "";
  try {
    results.value = (await adminUsers.search(q)).data;
    if (!results.value.length) searchError.value = t("safety.console.notices.noMatch");
  } catch (e) {
    results.value = [];
    toasts.error(e);
  } finally {
    searching.value = false;
  }
}

const rowLabel = (u: UserRow) => u.display_name || (u.handle ? `@${u.handle}` : u.email_masked);

async function send() {
  if (!canSend.value) return;
  sending.value = true;
  try {
    const notice = await adminService.sendNotice(
      recipients.value.map((r) => r.id),
      body.value.trim(),
    );
    sent.value = [notice, ...sent.value.filter((n) => n.id !== notice.id)];
    recipients.value = [];
    body.value = "";
    toasts.success(t("safety.console.notices.sent", { count: notice.recipient_count }, notice.recipient_count));
  } catch (e) {
    toasts.error(e, { validation_error: "safety.console.notices.invalid" });
  } finally {
    sending.value = false;
  }
}

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const page = await adminService.notices();
    sent.value = page.data;
    cursor.value = page.page.next_cursor;
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

async function more() {
  if (!cursor.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await adminService.notices(cursor.value);
    const known = new Set(sent.value.map((n) => n.id));
    sent.value = [...sent.value, ...page.data.filter((n) => !known.has(n.id))];
    cursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

onMounted(() => {
  const to = typeof route.query.to === "string" ? route.query.to : "";
  if (UUID.test(to)) add(to, typeof route.query.label === "string" && route.query.label ? route.query.label : to);
  void load();
});
</script>

<template>
  <AdminLayout :title="t('safety.console.sections.notices')" :subtitle="t('safety.console.notices.subtitle')">
    <form class="card mb-6 space-y-4 p-4" data-testid="notice-composer" @submit.prevent="send">
      <div>
        <p :id="`${uid}-to`" class="label">{{ t("safety.console.notices.to") }}</p>
        <ul v-if="recipients.length" class="mb-2 flex flex-wrap gap-2" :aria-labelledby="`${uid}-to`">
          <li v-for="r in recipients" :key="r.id" class="chip">
            <span class="max-w-[14rem] truncate" dir="auto">{{ r.label }}</span>
            <button type="button" class="rounded-full p-0.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('safety.console.notices.removeRecipient', { name: r.label })" @click="remove(r.id)">
              <X class="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </li>
        </ul>
        <p v-else class="mb-2 text-sm text-gray-500 dark:text-gray-400">{{ t("safety.console.notices.noRecipients") }}</p>

        <div v-if="canSearch" class="space-y-2">
          <div class="flex gap-2">
            <label :for="`${uid}-search`" class="sr-only">{{ t("safety.console.notices.search") }}</label>
            <input :id="`${uid}-search`" v-model="query" class="input" type="search" dir="auto" :placeholder="t('safety.console.notices.search')" @keydown.enter.prevent="search" />
            <button type="button" class="btn-soft shrink-0" :disabled="searching || !query.trim()" @click="search">
              <Search class="h-4 w-4" aria-hidden="true" /> {{ t("safety.console.notices.find") }}
            </button>
          </div>
          <p v-if="searchError" class="text-sm text-gray-500 dark:text-gray-400" role="status">{{ searchError }}</p>
          <ul v-if="results.length" class="divide-y divide-gray-100 rounded-xl border border-gray-100 dark:divide-gray-800 dark:border-gray-800">
            <li v-for="u in results" :key="u.account_id" class="flex items-center gap-2 px-3 py-2 text-sm">
              <span class="min-w-0 flex-1">
                <span class="block truncate font-medium" dir="auto">{{ rowLabel(u) }}</span>
                <span class="block truncate text-xs text-gray-500 dark:text-gray-400" dir="ltr">{{ u.email_masked }}</span>
              </span>
              <button type="button" class="btn-ghost text-sm" @click="add(u.account_id, rowLabel(u))">{{ t("safety.console.notices.add") }}</button>
            </li>
          </ul>
        </div>
        <div v-else class="flex gap-2">
          <label :for="`${uid}-id`" class="sr-only">{{ t("safety.console.notices.accountId") }}</label>
          <input :id="`${uid}-id`" v-model="pasted" class="input" dir="ltr" :placeholder="t('safety.console.notices.accountId')" @keydown.enter.prevent="addPasted" />
          <button type="button" class="btn-soft shrink-0" :disabled="!pasted.trim()" @click="addPasted">{{ t("safety.console.notices.add") }}</button>
        </div>
      </div>

      <div>
        <label :for="`${uid}-body`" class="label">{{ t("safety.console.notices.body") }}</label>
        <textarea :id="`${uid}-body`" v-model="body" class="input min-h-28" dir="auto" :maxlength="NOTICE_MAX_BODY" required :aria-describedby="`${uid}-body-hint`" />
        <p :id="`${uid}-body-hint`" class="mt-1 flex justify-between gap-2 text-xs text-gray-500 dark:text-gray-400">
          <span>{{ t("safety.console.notices.bodyHint") }}</span>
          <span dir="ltr" class="tabular-nums">{{ remaining }}</span>
        </p>
      </div>

      <div class="flex justify-end">
        <button type="submit" class="btn-primary" :disabled="!canSend" data-testid="notice-send">
          <Megaphone class="h-4 w-4" aria-hidden="true" />
          {{ sending ? t("states.loading") : t("safety.console.notices.send") }}
        </button>
      </div>
    </form>

    <section aria-labelledby="notices-history">
      <h2 id="notices-history" class="mb-2 font-semibold">{{ t("safety.console.notices.history") }}</h2>
      <LoadingSkeleton v-if="loading" :rows="2" />
      <ErrorState v-else-if="error" @retry="load" />
      <EmptyState v-else-if="!sent.length">{{ t("safety.console.notices.empty") }}</EmptyState>
      <ul v-else class="space-y-2" data-testid="notices-history">
        <li v-for="n in sent" :key="n.id" class="card p-3">
          <p class="whitespace-pre-wrap break-words text-sm" dir="auto">{{ n.body }}</p>
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {{ t("safety.console.notices.recipients", { count: n.recipient_count }, n.recipient_count) }} ·
            <time :datetime="n.created_at">{{ relativeTime(n.created_at) }}</time>
          </p>
        </li>
      </ul>
      <div v-if="cursor && !error" class="mt-2 flex justify-center">
        <button class="btn-ghost text-sm" :disabled="loadingMore" @click="more">{{ loadingMore ? t("states.loading") : t("feed.loadMore") }}</button>
      </div>
    </section>
  </AdminLayout>
</template>
