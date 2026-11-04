<script setup lang="ts">
// /pages/id/:id/inbox — a Page's messages, for its team (owner, admins,
// editors, moderators). Anyone else, a missing page or a page they cannot see
// gets the 404 page; the chat service answers 404 to them as well.
import { ArrowLeft } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import TeamInbox from "@/components/chat/TeamInbox.vue";
import AppShell from "@/components/layout/AppShell.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { httpStatus } from "@/lib/api";
import { type Page, pageService } from "@/services/pages";
import NotFoundView from "@/views/NotFoundView.vue";

const TEAM_ROLES = ["owner", "admin", "editor", "moderator"];

const { t } = useI18n();
const route = useRoute();
const page = ref<Page | null>(null);
const missing = ref(false);
const error = ref(false);

async function load() {
  error.value = false;
  try {
    const found = await pageService.getById(String(route.params.id));
    if (!TEAM_ROLES.includes(found.my_role ?? "")) missing.value = true;
    else page.value = found;
  } catch (e) {
    if (httpStatus(e) === 404 || httpStatus(e) === 400) missing.value = true;
    else error.value = true;
  }
}

onMounted(load);
</script>

<template>
  <NotFoundView v-if="missing" />
  <AppShell v-else :right="false">
    <ErrorState v-if="error" @retry="load" />
    <LoadingSkeleton v-else-if="!page" :rows="4" />
    <template v-else>
      <header class="mb-3 flex items-start gap-2">
        <RouterLink :to="`/pages/${page.handle}`" class="icon-btn h-9 w-9 shrink-0" :aria-label="page.name">
          <ArrowLeft class="h-5 w-5 rtl:rotate-180" aria-hidden="true" />
        </RouterLink>
        <div class="min-w-0">
          <h1 class="text-xl font-bold sm:text-2xl">{{ t("chatTeam.pageInbox") }}</h1>
          <p class="text-sm text-gray-500 dark:text-gray-400">{{ t("chatTeam.pageInboxHint") }}</p>
        </div>
      </header>
      <TeamInbox :page-id="page.id" :team-name="page.name" :open-id="typeof route.query.conversation === 'string' ? route.query.conversation : ''" />
    </template>
  </AppShell>
</template>
