<script setup lang="ts">
import { CalendarClock, CheckCircle2, Eye, Pencil, Send, Trash2, X } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import StudioPostThumb from "@/components/studio/StudioPostThumb.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { postTime, rescheduleProblem } from "@/lib/planner";
import { type ComposerPost, fromLocalInput, scheduleBounds, toLocalInput } from "@/services/composer";

// One post of the planner: what it is and when (in the viewer's zone), and its
// actions. The keyboard and touch way to move a scheduled post (no drag needed).
const props = defineProps<{ post: ComposerPost; zone: string; busy?: boolean }>();
const emit = defineEmits<{
  close: [];
  edit: [post: ComposerPost];
  reschedule: [post: ComposerPost, at: Date];
  publish: [post: ComposerPost];
  remove: [post: ComposerPost];
}>();

const { t, locale } = useI18n();
const panel = ref<HTMLElement | null>(null);
useFocusTrap(panel);
useEscapeKey(ref(true), () => emit("close"));

const scheduled = computed(() => props.post.state === "scheduled");
const at = computed(() => postTime(props.post));
const fmt = (iso: string) => new Intl.DateTimeFormat(locale.value, { dateStyle: "full", timeStyle: "short" }).format(new Date(iso));
const excerpt = computed(() => (props.post.body || "").trim() || t("studio.library.noText"));

const picking = ref(false);
const value = ref(toLocalInput(new Date(at.value)));
const bounds = scheduleBounds();
const confirming = ref(false);
const problem = computed(() => {
  const iso = fromLocalInput(value.value);
  return iso ? rescheduleProblem(new Date(iso)) : "past";
});
function save() {
  const iso = fromLocalInput(value.value);
  if (!iso || problem.value) return;
  emit("reschedule", props.post, new Date(iso));
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 p-0 backdrop-blur-sm sm:items-center sm:p-4" @click.self="emit('close')">
    <div
      ref="panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby="planner-dialog-title"
      tabindex="-1"
      class="card w-full max-w-md rounded-b-none p-4 sm:rounded-b-2xl"
      data-testid="planner-dialog"
    >
      <div class="flex items-center justify-between gap-2">
        <h2 id="planner-dialog-title" class="section-title">{{ t("studio.planner.details") }}</h2>
        <button type="button" class="icon-btn h-9 w-9" :aria-label="t('studio.planner.close')" @click="emit('close')"><X class="h-5 w-5" aria-hidden="true" /></button>
      </div>

      <div class="mt-3 flex items-start gap-3">
        <StudioPostThumb :type="post.type" :media-ids="post.media_ids" :size="56" />
        <div class="min-w-0 flex-1">
          <p class="line-clamp-3 text-sm font-semibold text-gray-900 dark:text-gray-100" dir="auto">{{ excerpt }}</p>
          <p class="mt-1 inline-flex items-center gap-1 text-xs font-semibold" :class="scheduled ? 'text-accent-700 dark:text-accent-300' : 'text-brand-700 dark:text-brand-300'">
            <CalendarClock v-if="scheduled" class="h-3.5 w-3.5" aria-hidden="true" />
            <CheckCircle2 v-else class="h-3.5 w-3.5" aria-hidden="true" />
            {{ scheduled ? t("studio.planner.scheduled") : t("studio.planner.published") }}
          </p>
          <p class="mt-1 text-sm text-gray-700 dark:text-gray-300" data-testid="planner-dialog-time">{{ fmt(at) }}</p>
          <p class="text-xs text-gray-500 dark:text-gray-400" dir="auto">{{ t("studio.library.zone", { zone }) }}</p>
          <p v-if="!scheduled" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {{ t("studio.planner.stats", { reactions: post.reaction_count, comments: post.comment_count, shares: post.share_count }) }}
          </p>
        </div>
      </div>

      <form v-if="scheduled && picking" class="mt-4 space-y-2" @submit.prevent="save">
        <label class="label" for="planner-new-time">{{ t("studio.planner.newTime") }}</label>
        <input id="planner-new-time" v-model="value" type="datetime-local" dir="ltr" class="input" :min="bounds.min" :max="bounds.max" data-testid="planner-new-time" />
        <p v-if="problem" class="text-xs text-red-600 dark:text-red-400" role="alert">
          {{ problem === "past" ? t("composer.errors.publishAtPast") : t("composer.errors.publishAtTooFar") }}
        </p>
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="picking = false">{{ t("studio.library.cancel") }}</button>
          <button type="submit" class="btn-primary" :disabled="busy || !!problem" data-testid="planner-save-time">{{ t("studio.planner.save") }}</button>
        </div>
      </form>

      <div v-else class="mt-4 flex flex-wrap gap-2">
        <template v-if="scheduled">
          <template v-if="confirming">
            <span class="self-center text-sm font-semibold text-red-600 dark:text-red-400">{{ t("studio.library.confirmDelete") }}</span>
            <button type="button" class="btn-danger" :disabled="busy" data-testid="planner-confirm-delete" @click="emit('remove', post)">{{ t("studio.library.delete") }}</button>
            <button type="button" class="btn-ghost" @click="confirming = false">{{ t("studio.library.cancel") }}</button>
          </template>
          <template v-else>
            <button type="button" class="btn-soft" data-testid="planner-reschedule" @click="picking = true">
              <CalendarClock class="h-4 w-4" aria-hidden="true" />{{ t("studio.planner.reschedule") }}
            </button>
            <button type="button" class="btn-ghost" data-testid="planner-edit" @click="emit('edit', post)">
              <Pencil class="h-4 w-4" aria-hidden="true" />{{ t("studio.library.edit") }}
            </button>
            <button type="button" class="btn-ghost" :disabled="busy" data-testid="planner-publish" @click="emit('publish', post)">
              <Send class="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" />{{ t("studio.library.publishNow") }}
            </button>
            <button type="button" class="btn-ghost text-red-600 dark:text-red-400" data-testid="planner-delete" @click="confirming = true">
              <Trash2 class="h-4 w-4" aria-hidden="true" />{{ t("studio.library.delete") }}
            </button>
          </template>
        </template>
        <RouterLink v-else :to="`/posts/${post.id}`" class="btn-soft" data-testid="planner-view">
          <Eye class="h-4 w-4" aria-hidden="true" />{{ t("studio.library.view") }}
        </RouterLink>
      </div>
    </div>
  </div>
</template>
