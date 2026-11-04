<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import AppShell from "@/components/layout/AppShell.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import { httpStatus } from "@/lib/api";
import { pageService } from "@/services/pages";
import NotFoundView from "@/views/NotFoundView.vue";

// /pages/id/:id — follows, saved items and page posts know a page by its id
// only: look it up (404 when hidden or gone) and replace the URL with its handle.
const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const missing = ref(false);
const error = ref(false);

async function resolve() {
  error.value = false;
  try {
    const page = await pageService.getById(String(route.params.id));
    router.replace({ name: "page", params: { handle: page.handle }, query: route.query });
  } catch (e) {
    if (httpStatus(e) === 404 || httpStatus(e) === 400) missing.value = true;
    else error.value = true;
  }
}

onMounted(resolve);
</script>

<template>
  <NotFoundView v-if="missing" />
  <AppShell v-else>
    <ErrorState v-if="error" @retry="resolve" />
    <p v-else class="card p-6 text-center text-sm text-gray-500 dark:text-gray-400" role="status">{{ t("pageHub.byId.resolving") }}</p>
  </AppShell>
</template>
