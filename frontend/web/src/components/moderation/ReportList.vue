<script setup lang="ts">
import { MessageSquareWarning, ShieldAlert } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { relativeTime } from "@/lib/format";
import { useSafetyLabels } from "@/lib/safetyLabels";
import { adminService, type ModerationReport, targetLink } from "@/services/admin";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";

/**
 * Raw reports, newest first: one case's (`caseId`) or every report (the
 * console's Reports tab). Each shows the reason the reporter chose, their own
 * words, when, who (a link to the account page for staff who may open it) and,
 * for a chat message, the text the reporter saw.
 */
const props = withDefaults(defineProps<{ caseId?: string | null; showTarget?: boolean }>(), { caseId: null, showTarget: false });

const { t, te } = useI18n();
// A system-sourced report (Tara Intelligence WP 7.4) names no person, only the signal.
const isSystem = (r: ModerationReport) => r.source === "system" || !r.reporter_id;
const signalText = (r: ModerationReport) => {
  const key = `myAlgorithm.moderation.signals.${r.evidence?.signal ?? r.reason}`;
  return te(key) ? t(key) : null;
};
const auth = useAuthStore();
const directory = useDirectoryStore();
const { reasonLabel, targetLabel, reasonDetail } = useSafetyLabels();

const rows = ref<ModerationReport[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const error = ref(false);
const loadingMore = ref(false);
const canOpenUsers = computed(() => auth.can("admin.users.view"));

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const page = await adminService.reports(props.caseId);
    rows.value = page.data;
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
    const page = await adminService.reports(props.caseId, cursor.value);
    const known = new Set(rows.value.map((r) => r.id));
    rows.value = [...rows.value, ...page.data.filter((r) => !known.has(r.id))];
    cursor.value = page.page.next_cursor;
  } catch {
    error.value = true;
  } finally {
    loadingMore.value = false;
  }
}

onMounted(load);
watch(() => props.caseId, load);
</script>

<template>
  <div data-testid="report-list">
    <LoadingSkeleton v-if="loading" :rows="2" />
    <ErrorState v-else-if="error && !rows.length" @retry="load" />
    <EmptyState v-else-if="!rows.length">{{ t("safety.mod.reports.empty") }}</EmptyState>
    <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800">
      <li v-for="r in rows" :key="r.id" class="py-3" data-testid="report-row">
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span v-if="isSystem(r)" class="chip border-accent-300 text-accent-800 dark:border-accent-700 dark:text-accent-200" data-testid="report-system">
            <ShieldAlert class="h-4 w-4" aria-hidden="true" /> {{ t("myAlgorithm.moderation.systemSignal") }}
          </span>
          <span v-else class="chip">{{ reasonLabel(r.reason) }}</span>
          <template v-if="showTarget">
            <RouterLink v-if="targetLink(r.target_type, r.target_id)" :to="targetLink(r.target_type, r.target_id)!" class="font-medium text-brand-700 hover:underline dark:text-brand-300">
              {{ targetLabel(r.target_type) }}<template v-if="r.target_type === 'user'"> · <bdi>{{ directory.label(r.target_id) }}</bdi></template>
            </RouterLink>
            <span v-else class="font-medium">{{ targetLabel(r.target_type) }}</span>
          </template>
          <time class="ms-auto text-xs text-gray-500 dark:text-gray-400" :datetime="r.created_at">{{ relativeTime(r.created_at) }}</time>
        </div>
        <template v-if="isSystem(r)">
          <p v-if="signalText(r)" class="mt-1.5 text-sm text-gray-700 dark:text-gray-200" data-testid="report-system-signal">{{ signalText(r) }}</p>
          <p v-if="Number.isInteger(r.evidence?.distinct_accounts)" class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
            {{ t("myAlgorithm.moderation.distinct", { count: r.evidence!.distinct_accounts }) }}
          </p>
        </template>
        <p v-else-if="reasonDetail(r.reason)" class="mt-1.5 whitespace-pre-wrap break-words text-sm text-gray-700 dark:text-gray-200" dir="auto">“{{ reasonDetail(r.reason) }}”</p>
        <blockquote
          v-if="r.evidence && r.evidence.body !== undefined"
          class="mt-2 rounded-xl border-s-4 border-accent-400 bg-gray-50 p-3 text-sm dark:bg-gray-950/60"
          data-testid="report-evidence"
        >
          <p class="mb-1 flex items-center gap-1.5 text-xs font-semibold text-gray-500 dark:text-gray-400">
            <MessageSquareWarning class="h-4 w-4" aria-hidden="true" /> {{ t("safety.mod.reports.evidence") }}
          </p>
          <p class="whitespace-pre-wrap break-words" dir="auto">{{ r.evidence.body || t("safety.mod.reports.evidenceBlank") }}</p>
          <p v-if="r.evidence.attachment_count" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {{ t("safety.mod.reports.attachments", { count: r.evidence.attachment_count }, r.evidence.attachment_count) }}
          </p>
        </blockquote>
        <p v-if="!isSystem(r)" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
          {{ t("safety.mod.reports.by") }}
          <!-- The reporter's name (ids share a time prefix, so a fragment tells nobody apart). -->
          <RouterLink
            v-if="r.reporter_id"
            :to="canOpenUsers ? `/admin/users/${r.reporter_id}` : `/u/id/${r.reporter_id}`"
            class="font-medium text-brand-700 hover:underline dark:text-brand-300"
            data-testid="report-reporter"
          ><bdi>{{ directory.label(r.reporter_id) }}</bdi></RouterLink>
        </p>
      </li>
    </ul>
    <div v-if="cursor" class="mt-2 flex justify-center">
      <button type="button" class="btn-ghost text-sm" :disabled="loadingMore" @click="more">{{ loadingMore ? t("states.loading") : t("feed.loadMore") }}</button>
    </div>
  </div>
</template>
