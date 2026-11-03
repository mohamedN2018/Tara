<script setup lang="ts">
import { Flag, Plus, X } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { errorMessage } from "@/lib/errors";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { type Page, pageService } from "@/services/pages";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const router = useRouter();
const toasts = useToastStore();

type Tab = "browse" | "mine";
const tab = ref<Tab>("browse");
const query = ref("");
const pages = ref<Page[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const page = await pageService.list({ q: query.value.trim(), mine: tab.value === "mine" });
    pages.value = page.data;
    cursor.value = page.page.next_cursor;
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

async function loadMore() {
  if (!cursor.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await pageService.list({
      q: query.value.trim(),
      mine: tab.value === "mine",
      cursor: cursor.value,
    });
    pages.value.push(...page.data);
    cursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

// ---- create ----
const showCreate = ref(false);
useEscapeKey(showCreate, () => (showCreate.value = false));
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
const form = ref({ name: "", handle: "", category: "", description: "", location: "" });
const creating = ref(false);
const createError = ref("");

async function create() {
  if (creating.value) return;
  creating.value = true;
  createError.value = "";
  try {
    const page = await pageService.create({
      ...form.value,
      name: form.value.name.trim(),
      handle: form.value.handle.trim(),
    });
    router.push({ name: "page", params: { handle: page.handle } });
  } catch (e) {
    createError.value = errorMessage(e, { conflict: "pages.handleTaken" });
  } finally {
    creating.value = false;
  }
}

watch(tab, load);
onMounted(load);
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[720px] space-y-4">
      <div class="flex items-center justify-between">
        <h1 class="text-xl font-bold">{{ t("pages.title") }}</h1>
        <button class="btn-primary" @click="showCreate = true"><Plus class="h-4 w-4" /> {{ t("pages.create") }}</button>
      </div>

      <div class="flex gap-1 rounded-xl bg-gray-100 p-1 text-sm dark:bg-gray-800">
        <button
          v-for="tb in (['browse', 'mine'] as Tab[])"
          :key="tb"
          class="flex-1 rounded-lg py-1.5 font-medium transition"
          :class="tab === tb ? 'bg-white text-brand-600 shadow-sm dark:bg-gray-900 dark:text-brand-300' : 'text-gray-500 dark:text-gray-400'"
          @click="tab = tb"
        >
          {{ t(`pages.${tb}`) }}
        </button>
      </div>

      <form @submit.prevent="load">
        <input v-model="query" class="input" type="search" dir="auto" :placeholder="t('pages.search')" :aria-label="t('pages.search')" />
      </form>

      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error" @retry="load" />
      <EmptyState v-else-if="!pages.length">{{ tab === "mine" ? t("pages.noneMine") : t("pages.none") }}</EmptyState>
      <ul v-else class="grid gap-3 sm:grid-cols-2">
        <li v-for="p in pages" :key="p.id">
          <RouterLink :to="{ name: 'page', params: { handle: p.handle } }" class="card block h-full p-4 transition hover:shadow-sm">
            <span class="flex items-center gap-2">
              <Flag class="h-4 w-4 shrink-0 text-brand-600 dark:text-brand-300" />
              <span class="truncate font-semibold" dir="auto">{{ p.name }}</span>
            </span>
            <span class="mt-0.5 block text-xs text-gray-500 dark:text-gray-400" dir="ltr">@{{ p.handle }}</span>
            <span v-if="p.category" class="mt-1 block text-xs text-gray-500 dark:text-gray-400" dir="auto">{{ p.category }}</span>
            <span v-if="p.my_role" class="mt-1 inline-block rounded-full bg-brand-50 px-2 py-0.5 text-xs text-brand-700 dark:bg-brand-950 dark:text-brand-300">
              {{ t(`pages.roles.${p.my_role}`) }}
            </span>
          </RouterLink>
        </li>
      </ul>
      <button v-if="!loading && cursor" class="btn-ghost mx-auto block" :disabled="loadingMore" @click="loadMore">
        {{ loadingMore ? t("states.loading") : t("states.loadMore") }}
      </button>
    </div>

    <div v-if="showCreate" class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 backdrop-blur-sm p-0 sm:items-center sm:p-4">
      <div class="fixed inset-0" @click="showCreate = false" />
      <div
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="page-dialog-title"
        tabindex="-1"
        class="card relative z-10 animate-pop-in shadow-pop max-h-[92vh] w-full overflow-y-auto rounded-b-none rounded-t-2xl p-4 sm:max-w-md sm:rounded-2xl sm:p-5"
      >
        <div class="mb-4 flex items-center justify-between">
          <h2 id="page-dialog-title" class="text-lg font-bold">{{ t("pages.create") }}</h2>
          <button class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('market.close')" @click="showCreate = false">
            <X class="h-5 w-5" />
          </button>
        </div>
        <form class="space-y-3" @submit.prevent="create">
          <div>
            <label for="page-name" class="mb-1 block text-sm font-medium">{{ t("pages.name") }}</label>
            <input id="page-name" v-model="form.name" class="input" dir="auto" maxlength="120" required />
          </div>
          <div>
            <label for="page-handle" class="mb-1 block text-sm font-medium">{{ t("pages.handle") }}</label>
            <input id="page-handle" v-model="form.handle" class="input" dir="ltr" pattern="[a-zA-Z0-9_]{3,30}" required :title="t('pages.handleHint')" />
          </div>
          <div>
            <label for="page-category" class="mb-1 block text-sm font-medium">{{ t("pages.category") }}</label>
            <input id="page-category" v-model="form.category" class="input" dir="auto" maxlength="80" />
          </div>
          <div>
            <label for="page-location" class="mb-1 block text-sm font-medium">{{ t("pages.location") }}</label>
            <input id="page-location" v-model="form.location" class="input" dir="auto" maxlength="160" />
          </div>
          <div>
            <label for="page-description" class="mb-1 block text-sm font-medium">{{ t("pages.description") }}</label>
            <textarea id="page-description" v-model="form.description" class="input min-h-20" dir="auto" rows="3" />
          </div>
          <p v-if="createError" class="text-sm text-red-500">{{ createError }}</p>
          <div class="flex justify-end gap-2">
            <button type="button" class="btn-ghost" @click="showCreate = false">{{ t("feed.cancel") }}</button>
            <button type="submit" class="btn-primary" :disabled="creating">{{ t("pages.create") }}</button>
          </div>
        </form>
      </div>
    </div>
  </AppShell>
</template>
