<script setup lang="ts">
import { Search } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AdminLayout from "@/components/admin/AdminLayout.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { SEARCH_FIELDS, type SearchField, type UserRow, accountLabel, adminUsers } from "@/services/adminUsers";
import { useToastStore } from "@/stores/toasts";

const { t, te, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const toasts = useToastStore();

// The query lives in the URL, so "back" from an account returns to the same results.
const q = ref(typeof route.query.q === "string" ? route.query.q : "");
const field = ref<SearchField>(SEARCH_FIELDS.includes(route.query.field as SearchField) ? (route.query.field as SearchField) : "auto");

const rows = ref<UserRow[]>([]);
const cursor = ref<string | null>(null);
const searched = ref(false);
const loading = ref(false);
const loadingMore = ref(false);
const error = ref(false);

const statusLabel = (status: string) => (te(`admin.users.status.${status}`) ? t(`admin.users.status.${status}`) : status);
const date = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : new Intl.DateTimeFormat(locale.value, { dateStyle: "medium" }).format(d);
};

async function load() {
  const term = q.value.trim();
  if (term.length < 2) {
    rows.value = [];
    searched.value = false;
    return;
  }
  loading.value = true;
  error.value = false;
  try {
    const page = await adminUsers.search(term, field.value);
    rows.value = page.data;
    cursor.value = page.page.next_cursor;
    searched.value = true;
  } catch (e) {
    error.value = true;
    toasts.error(e);
  } finally {
    loading.value = false;
  }
}

function submit() {
  const query: Record<string, string> = { q: q.value.trim() };
  if (field.value !== "auto") query.field = field.value;
  void router.replace({ query });
}

async function more() {
  if (!cursor.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await adminUsers.search(q.value.trim(), field.value, cursor.value);
    const known = new Set(rows.value.map((r) => r.account_id));
    rows.value = [...rows.value, ...page.data.filter((r) => !known.has(r.account_id))];
    cursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

watch(
  () => [route.query.q, route.query.field],
  () => {
    q.value = typeof route.query.q === "string" ? route.query.q : "";
    field.value = SEARCH_FIELDS.includes(route.query.field as SearchField) ? (route.query.field as SearchField) : "auto";
    void load();
  },
);

onMounted(load);
</script>

<template>
  <AdminLayout :title="t('admin.sections.users')">

    <section aria-labelledby="users-title">
      <!-- The page title already says "Users": the section heading is for screen readers. -->
      <h2 id="users-title" class="sr-only">{{ t("admin.users.title") }}</h2>

      <form role="search" class="card mb-4 flex flex-wrap items-end gap-2 p-3" :aria-label="t('admin.users.searchLabel')" @submit.prevent="submit">
        <label class="flex min-w-48 flex-1 flex-col gap-1 text-sm">
          {{ t("admin.users.searchLabel") }}
          <input v-model="q" type="search" class="input" dir="auto" minlength="2" maxlength="254" required :placeholder="t('admin.users.searchHint')" />
        </label>
        <label class="flex flex-col gap-1 text-sm">
          {{ t("admin.users.field") }}
          <select v-model="field" class="input w-auto">
            <option v-for="f in SEARCH_FIELDS" :key="f" :value="f">{{ t(`admin.users.fields.${f}`) }}</option>
          </select>
        </label>
        <button type="submit" class="btn-primary inline-flex shrink-0 items-center gap-1.5">
          <Search class="h-4 w-4" aria-hidden="true" /> {{ t("admin.users.search") }}
        </button>
      </form>

      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error" @retry="load" />
      <EmptyState v-else-if="!searched">{{ t("admin.users.prompt") }}</EmptyState>
      <EmptyState v-else-if="rows.length === 0">{{ t("admin.users.empty") }}</EmptyState>
      <div v-else class="card overflow-x-auto">
        <table class="w-full border-collapse text-sm" data-testid="user-results">
          <caption class="sr-only">{{ t("admin.users.title") }}</caption>
          <thead>
            <tr class="text-xs text-gray-500 dark:text-gray-400">
              <th scope="col" class="px-3 py-2 text-start font-semibold">{{ t("admin.users.columns.account") }}</th>
              <th scope="col" class="px-3 py-2 text-start font-semibold">{{ t("admin.users.columns.email") }}</th>
              <th scope="col" class="px-3 py-2 text-start font-semibold">{{ t("admin.users.columns.status") }}</th>
              <th scope="col" class="px-3 py-2 text-start font-semibold">{{ t("admin.users.columns.created") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.account_id" class="border-t border-gray-100 dark:border-gray-800" :data-account="r.account_id">
              <td class="px-3 py-2">
                <RouterLink :to="`/admin/users/${r.account_id}`" class="font-medium text-brand-700 hover:underline dark:text-brand-300" dir="auto">
                  {{ accountLabel(r) || t("admin.users.noName") }}
                </RouterLink>
                <span v-if="r.handle && r.display_name" class="block text-xs text-gray-500 dark:text-gray-400" dir="ltr">@{{ r.handle }}</span>
              </td>
              <td class="px-3 py-2"><span dir="ltr">{{ r.email_masked }}</span></td>
              <td class="px-3 py-2">
                <span
                  class="rounded-full px-2 py-0.5 text-xs font-medium"
                  :class="
                    r.status === 'suspended'
                      ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300'
                      : r.status === 'active'
                        ? 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300'
                        : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
                  "
                >
                  {{ statusLabel(r.status) }}
                </span>
              </td>
              <td class="whitespace-nowrap px-3 py-2">
                <time v-if="r.created_at" :datetime="r.created_at">{{ date(r.created_at) }}</time>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="cursor && !loading && !error" class="mt-3 flex justify-center">
        <button type="button" class="btn-ghost text-sm" :disabled="loadingMore" @click="more">
          {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
        </button>
      </div>
    </section>
  </AdminLayout>
</template>
