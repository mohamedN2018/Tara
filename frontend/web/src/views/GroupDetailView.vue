<script setup lang="ts">
import { CalendarPlus, Lock } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import EventCard from "@/components/events/EventCard.vue";
import GroupHeader from "@/components/groups/GroupHeader.vue";
import GroupInviteDialog from "@/components/groups/GroupInviteDialog.vue";
import GroupMediaTab from "@/components/groups/GroupMediaTab.vue";
import GroupMemberList from "@/components/groups/GroupMemberList.vue";
import GroupPostList from "@/components/groups/GroupPostList.vue";
import GroupReportDialog from "@/components/groups/GroupReportDialog.vue";
import PrivacyBadge from "@/components/groups/PrivacyBadge.vue";
import AppShell from "@/components/layout/AppShell.vue";
import CreatePostCard from "@/components/post/CreatePostCard.vue";
import MyPendingPosts from "@/components/post/MyPendingPosts.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import NotFoundView from "@/views/NotFoundView.vue";
import { httpStatus } from "@/lib/api";
import { eventsService, type TaraEvent } from "@/services/events";
import { type Group, groupsService } from "@/services/groups";
import { useToastStore } from "@/stores/toasts";
import type { Post } from "@/types";

// /groups/:handle — the group's page: header, then Discussion, Featured
// (announcements), Members, Events, Media and About. People who may not read
// the content (a private group they are not in) see the header and About.
type Tab = "discussion" | "featured" | "members" | "events" | "media" | "about";
const TABS: Tab[] = ["discussion", "featured", "members", "events", "media", "about"];

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const toasts = useToastStore();

const group = ref<Group | null>(null);
const loading = ref(true);
const missing = ref(false);
const error = ref(false);
const dialog = ref<"invite" | "report" | null>(null);
const version = ref(0);
const events = ref<TaraEvent[]>([]);
const eventsLoading = ref(false);
const postList = ref<InstanceType<typeof GroupPostList> | null>(null);
const myPending = ref<InstanceType<typeof MyPendingPosts> | null>(null);

const visibleTabs = computed<Tab[]>(() => (group.value?.content_visible ? TABS : ["about"]));
const isTab = (v: unknown): v is Tab => typeof v === "string" && (TABS as string[]).includes(v);
const tab = computed<Tab>(() => {
  const wanted = isTab(route.query.tab) ? route.query.tab : "discussion";
  return visibleTabs.value.includes(wanted) ? wanted : visibleTabs.value[0];
});
const isMember = computed(() => group.value?.viewer.state === "active");
const created = computed(() =>
  group.value ? new Date(group.value.created_at).toLocaleDateString(locale.value === "ar" ? "ar-EG" : "en-GB", { dateStyle: "long" }) : "",
);

async function load() {
  loading.value = !group.value;
  missing.value = false;
  error.value = false;
  try {
    group.value = await groupsService.get(String(route.params.handle));
  } catch (e) {
    if (httpStatus(e) === 404) {
      missing.value = true;
      group.value = null;
    } else error.value = true;
  } finally {
    loading.value = false;
  }
}

async function loadEvents() {
  if (!group.value?.content_visible) return;
  eventsLoading.value = true;
  try {
    events.value = (await eventsService.forGroup(group.value.id)).data;
  } catch (e) {
    events.value = [];
    toasts.error(e);
  } finally {
    eventsLoading.value = false;
  }
}

function pick(next: Tab) {
  router.replace({ query: { ...route.query, tab: next === "discussion" ? undefined : next } });
}

function focusTab(e: KeyboardEvent, index: number) {
  const rtl = document.documentElement.dir === "rtl";
  const step = { ArrowRight: rtl ? -1 : 1, ArrowLeft: rtl ? 1 : -1 }[e.key];
  if (!step) return;
  e.preventDefault();
  const list = visibleTabs.value;
  const next = list[(index + step + list.length) % list.length];
  pick(next);
  (document.getElementById(`group-tab-${next}`) as HTMLElement | null)?.focus();
}

function onPosted(post: Post) {
  if (post.approval_state === "pending") {
    toasts.success(t("groups.post.pendingToast"));
    void myPending.value?.refresh();
  }
  else postList.value?.prepend(post);
}

async function changed() {
  await load();
  version.value++;
}

watch(() => route.params.handle, () => {
  group.value = null;
  load();
}, { immediate: true });
watch(() => [tab.value, group.value?.id], () => {
  if (tab.value === "events") loadEvents();
});
</script>

<template>
  <NotFoundView v-if="missing" />
  <AppShell v-else :right="false">
    <div class="mx-auto w-full max-w-[940px] space-y-4">
      <LoadingSkeleton v-if="loading" :rows="3" />
      <ErrorState v-else-if="error || !group" @retry="load" />
      <template v-else>
        <GroupHeader :group="group" @changed="changed" @invite="dialog = 'invite'" @report="dialog = 'report'" />

        <div
          class="card flex gap-1 overflow-x-auto p-1 text-sm"
          role="tablist"
          :aria-label="t('groups.tabs.label')"
        >
          <button
            v-for="(x, i) in visibleTabs"
            :id="`group-tab-${x}`"
            :key="x"
            type="button"
            role="tab"
            :aria-selected="tab === x"
            :tabindex="tab === x ? 0 : -1"
            aria-controls="group-panel"
            class="relative whitespace-nowrap rounded-lg px-4 py-2 font-semibold transition"
            :class="tab === x ? 'text-brand-600 after:absolute after:inset-x-3 after:bottom-0 after:h-[3px] after:rounded-full after:bg-tara-gradient dark:text-brand-300' : 'text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800'"
            @click="pick(x)"
            @keydown="focusTab($event, i)"
          >
            {{ t(`groups.tabs.${x}`) }}
          </button>
        </div>

        <div id="group-panel" role="tabpanel" :aria-labelledby="`group-tab-${tab}`" class="space-y-4">
          <div v-if="!group.content_visible" class="card flex items-start gap-3 p-4" role="note">
            <Lock class="mt-0.5 h-5 w-5 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
            <div>
              <p class="font-semibold">{{ t("groups.locked.title") }}</p>
              <p class="text-sm text-gray-600 dark:text-gray-300">{{ t("groups.locked.body") }}</p>
            </div>
          </div>

          <template v-if="tab === 'discussion'">
            <CreatePostCard v-if="isMember && group.viewer.can.post" :group-id="group.id" :group-name="group.name" @created="onPosted" />
            <p v-if="isMember && group.post_approval && !group.viewer.can.approve_posts" class="px-1 text-xs text-gray-500 dark:text-gray-400">
              {{ t("groups.post.approvalHint") }}
            </p>
            <!-- T4: the member's own posts waiting for approval. -->
            <MyPendingPosts v-if="isMember && !group.viewer.can.approve_posts" ref="myPending" :group="group" :version="version" />
            <GroupPostList ref="postList" :group="group" view="discussion" :version="version" />
          </template>

          <GroupPostList v-else-if="tab === 'featured'" :group="group" view="featured" :version="version" />

          <div v-else-if="tab === 'members'" class="card p-4">
            <h2 class="section-title mb-3">{{ t("groups.memberCount", { count: group.member_count }, group.member_count) }}</h2>
            <GroupMemberList :group="group" state="active" />
          </div>

          <div v-else-if="tab === 'events'" class="space-y-3">
            <div v-if="isMember" class="flex justify-end">
              <RouterLink :to="{ path: '/events/new', query: { group: group.id } }" class="btn-soft">
                <CalendarPlus class="h-4 w-4" aria-hidden="true" /> {{ t("groups.events.create") }}
              </RouterLink>
            </div>
            <LoadingSkeleton v-if="eventsLoading" :rows="2" />
            <EmptyState v-else-if="!events.length">{{ t("groups.empty.events") }}</EmptyState>
            <div v-else class="grid gap-3 sm:grid-cols-2">
              <EventCard v-for="e in events" :key="e.id" :event="e" />
            </div>
          </div>

          <GroupMediaTab v-else-if="tab === 'media'" :group="group" />

          <section v-else class="card space-y-4 p-4 sm:p-6" aria-labelledby="group-about-title">
            <h2 id="group-about-title" class="section-title">{{ t("groups.about.title") }}</h2>
            <p v-if="group.description" class="whitespace-pre-line break-words text-sm leading-relaxed" dir="auto">{{ group.description }}</p>
            <dl class="grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("groups.form.privacy") }}</dt>
                <dd class="space-y-0.5">
                  <PrivacyBadge :privacy="group.privacy" />
                  <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t(`groups.privacyHints.${group.privacy}`) }}</span>
                </dd>
              </div>
              <div>
                <dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("groups.form.category") }}</dt>
                <dd>{{ t(`groups.categories.${group.category}`) }}</dd>
              </div>
              <div>
                <dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("groups.about.created") }}</dt>
                <dd>{{ created }}</dd>
              </div>
              <div>
                <dt class="text-xs text-gray-500 dark:text-gray-400">{{ t("groups.about.url") }}</dt>
                <dd dir="ltr" class="text-start">/groups/{{ group.handle }}</dd>
              </div>
            </dl>
            <div>
              <h3 class="mb-2 font-bold">{{ t("groups.rules.title") }}</h3>
              <ol v-if="group.rules?.length" class="space-y-2">
                <li v-for="(rule, i) in group.rules" :key="rule.id" class="flex gap-2">
                  <span class="font-bold text-brand-600 dark:text-brand-300">{{ i + 1 }}</span>
                  <div>
                    <p class="font-semibold" dir="auto">{{ rule.title }}</p>
                    <p v-if="rule.body" class="whitespace-pre-line text-sm text-gray-600 dark:text-gray-300" dir="auto">{{ rule.body }}</p>
                  </div>
                </li>
              </ol>
              <p v-else class="text-sm text-gray-500 dark:text-gray-400">{{ t("groups.rules.none") }}</p>
            </div>
          </section>
        </div>
      </template>
    </div>

    <GroupInviteDialog v-if="dialog === 'invite' && group" :group-ref="group.handle || group.id" @close="dialog = null" />
    <GroupReportDialog v-if="dialog === 'report' && group" :group-ref="group.handle || group.id" @close="dialog = null" @reported="dialog = null" />
  </AppShell>
</template>
