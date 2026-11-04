<script setup lang="ts">
import { ArrowLeft, Ban, FileClock, Flag, ListOrdered, MailQuestion, Settings2, UserCheck, Users } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import GroupMemberList from "@/components/groups/GroupMemberList.vue";
import GroupPostList from "@/components/groups/GroupPostList.vue";
import GroupSettings from "@/components/groups/GroupSettings.vue";
import ManageReports from "@/components/groups/ManageReports.vue";
import RulesEditor from "@/components/groups/RulesEditor.vue";
import AppShell from "@/components/layout/AppShell.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import NotFoundView from "@/views/NotFoundView.vue";
import { httpStatus } from "@/lib/api";
import { type Group, groupPath, groupsService, type ManageSection, manageSections } from "@/services/groups";

// /groups/:handle/manage — the Group Management Dashboard. Each section shows
// only when the backend says the viewer may use it (`viewer.can`), and every
// action is checked again on the server.
const { t } = useI18n();
const route = useRoute();
const router = useRouter();

const group = ref<Group | null>(null);
const loading = ref(true);
const missing = ref(false);
const error = ref(false);
const version = ref(0);

const ICONS: Record<ManageSection, typeof Users> = {
  requests: UserCheck,
  invited: MailQuestion,
  posts: FileClock,
  members: Users,
  banned: Ban,
  rules: ListOrdered,
  settings: Settings2,
  reports: Flag,
};
const sections = computed(() => manageSections(group.value?.viewer.can));
const section = computed<ManageSection | null>(() => {
  const wanted = route.query.section as ManageSection | undefined;
  return wanted && sections.value.includes(wanted) ? wanted : (sections.value[0] ?? null);
});

async function load() {
  loading.value = !group.value;
  missing.value = false;
  error.value = false;
  try {
    const g = await groupsService.get(String(route.params.handle));
    if (!manageSections(g.viewer.can).length) {
      router.replace(groupPath(g));
      return;
    }
    group.value = g;
  } catch (e) {
    if (httpStatus(e) === 404) missing.value = true;
    else error.value = true;
  } finally {
    loading.value = false;
  }
}

function pick(next: ManageSection) {
  router.replace({ query: { ...route.query, section: next } });
}

function saved(g: Group) {
  group.value = g;
}

async function refresh() {
  await load();
  version.value++;
}

watch(() => route.params.handle, () => {
  group.value = null;
  load();
}, { immediate: true });
</script>

<template>
  <NotFoundView v-if="missing" />
  <AppShell v-else :right="false">
    <div class="mx-auto w-full max-w-[1100px] space-y-4">
      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error || !group" @retry="load" />
      <div v-else class="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside class="card h-fit space-y-3 p-3 lg:sticky lg:top-20">
          <RouterLink :to="groupPath(group)" class="btn-ghost w-full justify-start">
            <ArrowLeft class="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
            <span class="truncate"><bdi>{{ group.name }}</bdi></span>
          </RouterLink>
          <h1 class="px-2 text-lg font-bold">{{ t("groups.manage.title") }}</h1>
          <nav class="flex gap-1 overflow-x-auto lg:flex-col" :aria-label="t('groups.manage.title')">
            <button
              v-for="s in sections"
              :key="s"
              type="button"
              class="nav-item shrink-0 whitespace-nowrap"
              :class="section === s ? 'nav-item-active' : ''"
              :aria-current="section === s ? 'page' : undefined"
              @click="pick(s)"
            >
              <component :is="ICONS[s]" class="h-5 w-5 shrink-0" aria-hidden="true" />
              {{ t(`groups.manage.sections.${s}`) }}
            </button>
          </nav>
        </aside>

        <section v-if="section" class="card min-w-0 space-y-4 p-4 sm:p-6" aria-labelledby="group-manage-section">
          <div>
            <h2 id="group-manage-section" class="text-xl font-bold">{{ t(`groups.manage.sections.${section}`) }}</h2>
            <p class="text-sm text-gray-500 dark:text-gray-400">{{ t(`groups.manage.hints.${section}`) }}</p>
          </div>
          <GroupMemberList v-if="section === 'requests'" :key="`requests-${version}`" :group="group" state="requested" manage @changed="refresh" />
          <GroupMemberList v-else-if="section === 'invited'" :key="`invited-${version}`" :group="group" state="invited" manage @changed="refresh" />
          <GroupPostList v-else-if="section === 'posts'" :group="group" view="pending" :version="version" />
          <GroupMemberList v-else-if="section === 'members'" :key="`members-${version}`" :group="group" state="active" manage @changed="refresh" />
          <GroupMemberList v-else-if="section === 'banned'" :key="`banned-${version}`" :group="group" state="banned" manage @changed="refresh" />
          <RulesEditor v-else-if="section === 'rules'" :group="group" />
          <GroupSettings v-else-if="section === 'settings'" :group="group" @saved="saved" />
          <ManageReports v-else-if="section === 'reports'" :group="group" />
        </section>
      </div>
    </div>
  </AppShell>
</template>
