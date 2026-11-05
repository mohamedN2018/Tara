<script setup lang="ts">
import { CalendarDays, History, Info, X } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { pageCategoryLabel } from "@/lib/pageCategory";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { type Page, pageService, type PageTransparency } from "@/services/pages";

// "Page transparency" (plan 08): when the page was created, its category and
// the names it had before. The profile service answers only for a page the
// viewer may see; who renamed it is never sent.
const props = defineProps<{ page: Page }>();
const emit = defineEmits<{ close: [] }>();
const i18n = useI18n();
const { t, locale } = i18n;

const info = ref<PageTransparency | null>(null);
const failed = ref(false);
async function load() {
  failed.value = false;
  try {
    info.value = await pageService.transparency(props.page.id);
  } catch {
    failed.value = true;
  }
}
onMounted(load);

const fmtDate = (iso: string) => {
  try {
    return new Intl.DateTimeFormat(locale.value, { year: "numeric", month: "long", day: "numeric" }).format(new Date(iso));
  } catch {
    return iso.slice(0, 10);
  }
};

const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
useEscapeKey(ref(true), () => emit("close"));
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[75] flex items-end justify-center bg-gray-950/60 backdrop-blur-sm sm:items-center sm:p-4">
      <div class="fixed inset-0" @click="emit('close')" />
      <div
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="page-transparency-title"
        tabindex="-1"
        class="card relative z-10 flex max-h-[85vh] w-full flex-col rounded-b-none p-4 shadow-pop sm:max-w-md sm:rounded-2xl sm:p-5"
        data-testid="page-transparency"
      >
        <div class="mb-1 flex items-center justify-between gap-2">
          <h2 id="page-transparency-title" class="text-lg font-bold">{{ t("profileTools.page.transparency") }}</h2>
          <button type="button" class="icon-btn h-9 w-9" :aria-label="t('profileTools.page.close')" @click="emit('close')">
            <X class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <p class="mb-4 text-sm text-gray-600 dark:text-gray-400">{{ t("profileTools.page.transparencyHint") }}</p>

        <div class="min-h-0 flex-1 overflow-y-auto">
          <ErrorState v-if="failed" :message="t('profileTools.page.loadFailed')" @retry="load" />
          <LoadingSkeleton v-else-if="!info" :rows="2" />
          <div v-else class="space-y-4 text-sm">
            <div class="flex items-start gap-3">
              <CalendarDays class="mt-0.5 h-5 w-5 shrink-0 text-gray-500 dark:text-gray-400" aria-hidden="true" />
              <div>
                <h3 class="font-semibold">{{ t("profileTools.page.created") }}</h3>
                <div class="text-gray-700 dark:text-gray-300" data-testid="page-transparency-created">{{ fmtDate(info.created_at) }}</div>
              </div>
            </div>
            <div class="flex items-start gap-3">
              <Info class="mt-0.5 h-5 w-5 shrink-0 text-gray-500 dark:text-gray-400" aria-hidden="true" />
              <div>
                <h3 class="font-semibold">{{ t("profileTools.page.category") }}</h3>
                <div class="text-gray-700 dark:text-gray-300">
                  <bdi>{{ info.category ? pageCategoryLabel(info.category, i18n) : t("profileTools.page.noCategory") }}</bdi>
                </div>
              </div>
            </div>
            <div class="flex items-start gap-3">
              <History class="mt-0.5 h-5 w-5 shrink-0 text-gray-500 dark:text-gray-400" aria-hidden="true" />
              <div class="min-w-0 flex-1">
                <h3 class="font-semibold">{{ t("profileTools.page.nameHistory") }}</h3>
                <div v-if="!info.name_changes.length" class="text-gray-700 dark:text-gray-300" data-testid="page-transparency-no-renames">
                  {{ t("profileTools.page.noNameChanges") }}
                </div>
                <div v-else>
                  <ol class="mt-1 space-y-2" data-testid="page-transparency-renames">
                    <li v-for="(c, i) in info.name_changes" :key="i" class="rounded-lg bg-gray-50 p-2.5 dark:bg-gray-800/60">
                      <p><span class="text-gray-600 dark:text-gray-400">{{ t("profileTools.page.renamedTo") }}</span> <bdi class="font-semibold">{{ c.new_name }}</bdi></p>
                      <p><span class="text-gray-600 dark:text-gray-400">{{ t("profileTools.page.renamedFrom") }}</span> <bdi>{{ c.old_name }}</bdi></p>
                      <p class="text-xs text-gray-600 dark:text-gray-400">{{ fmtDate(c.changed_at) }}</p>
                    </li>
                  </ol>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
