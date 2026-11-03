<script setup lang="ts">
import { Check, ExternalLink, Trash2 } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { relativeTime } from "@/lib/format";
import { type Group, groupPostsService, type GroupReportItem } from "@/services/groups";
import { postService } from "@/services/post";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

// Posts and comments in this group that members reported. Staff remove them
// or keep them (dismiss); platform moderation still has its own queue.
const props = defineProps<{ group: Group }>();

const { t, locale } = useI18n();
const directory = useDirectoryStore();
const toasts = useToastStore();
const items = ref<GroupReportItem[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const error = ref(false);
const busy = ref<string | null>(null);

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const page = await groupPostsService.reports(props.group.id);
    items.value = page.data;
    cursor.value = page.page.next_cursor;
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

async function more() {
  if (!cursor.value) return;
  try {
    const page = await groupPostsService.reports(props.group.id, cursor.value);
    items.value = [...items.value, ...page.data];
    cursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  }
}

async function act(item: GroupReportItem, remove: boolean) {
  if (busy.value) return;
  if (remove && !window.confirm(t("groups.reports.removeConfirm"))) return;
  busy.value = item.target_id;
  try {
    if (!remove) await groupPostsService.dismissReport(props.group.id, item.target_type, item.target_id);
    else if (item.target_type === "post") await postService.remove(item.target_id);
    else await postService.deleteComment(item.target_id);
    items.value = items.value.filter((x) => x.target_id !== item.target_id);
    toasts.success(t(remove ? "groups.reports.removed" : "groups.reports.kept"));
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = null;
  }
}

onMounted(load);
</script>

<template>
  <div>
    <LoadingSkeleton v-if="loading" :rows="2" />
    <ErrorState v-else-if="error" @retry="load" />
    <EmptyState v-else-if="!items.length">{{ t("groups.empty.reports") }}</EmptyState>
    <ul v-else class="space-y-2">
      <li v-for="item in items" :key="item.target_id" class="rounded-xl border border-gray-200 p-3 dark:border-gray-800">
        <div class="flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
          <span class="font-semibold text-gray-700 dark:text-gray-200">{{ t(`groups.reports.types.${item.target_type}`) }}</span>
          <span aria-hidden="true">·</span>
          <span dir="auto">{{ directory.label(item.author_id) }}</span>
          <span aria-hidden="true">·</span>
          <span>{{ t("groups.reports.count", { count: item.report_count }, item.report_count) }}</span>
          <span aria-hidden="true">·</span>
          <span>{{ relativeTime(item.last_reported_at) }}</span>
        </div>
        <p v-if="item.excerpt" class="mt-1 line-clamp-3 whitespace-pre-line text-sm" dir="auto">{{ item.excerpt }}</p>
        <p v-if="item.reasons.length" class="mt-1 text-xs text-gray-500 dark:text-gray-400" dir="auto">
          {{ t("groups.reports.reasons") }}: {{ item.reasons.join(locale === "ar" ? "، " : ", ") }}
        </p>
        <div class="mt-2 flex flex-wrap justify-end gap-2">
          <RouterLink :to="`/posts/${item.post_id}`" class="btn-ghost text-sm">
            <ExternalLink class="h-4 w-4" aria-hidden="true" /> {{ t("groups.reports.open") }}
          </RouterLink>
          <button type="button" class="btn-outline" :disabled="busy === item.target_id" @click="act(item, false)">
            <Check class="h-4 w-4" aria-hidden="true" /> {{ t("groups.reports.keep") }}
          </button>
          <button type="button" class="btn-danger" :disabled="busy === item.target_id" @click="act(item, true)">
            <Trash2 class="h-4 w-4" aria-hidden="true" /> {{ t("groups.reports.remove") }}
          </button>
        </div>
      </li>
    </ul>
    <button v-if="cursor" class="btn-ghost mx-auto mt-3 block" @click="more">{{ t("states.loadMore") }}</button>
  </div>
</template>
