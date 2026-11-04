<script setup lang="ts">
import { Check, X } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import { AUDIENCES } from "@/lib/audiences";
import { errorMessage } from "@/lib/errors";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { postService } from "@/services/post";
import type { Post } from "@/types";

// "Edit audience" on a published post (author only; the server checks it and
// refuses a share wider than its original).
const props = withDefaults(defineProps<{ postId: string; audience: string; isShare?: boolean }>(), { isShare: false });
const emit = defineEmits<{ close: []; updated: [post: Post] }>();

const { t } = useI18n();
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
useEscapeKey(ref(true), () => emit("close"));

const busy = ref(false);
const error = ref("");
const AUDIENCE_ERRORS = { validation_error: "postsFeed.audience.shareLimit" };

async function pick(v: string) {
  if (busy.value) return;
  if (v === props.audience) {
    emit("close");
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    emit("updated", await postService.update(props.postId, { audience: v }));
    emit("close");
  } catch (e) {
    error.value = errorMessage(e, props.isShare ? AUDIENCE_ERRORS : {});
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[60] flex items-end justify-center bg-gray-950/60 backdrop-blur-sm sm:items-center sm:p-4">
      <div class="fixed inset-0" aria-hidden="true" @click="emit('close')" />
      <div
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="audience-dialog-title"
        tabindex="-1"
        class="card relative z-10 w-full animate-pop-in rounded-b-none rounded-t-2xl p-0 shadow-pop sm:max-w-sm sm:rounded-2xl"
        data-testid="audience-dialog"
      >
        <div class="relative flex items-center justify-center border-b border-gray-100 px-12 py-3 dark:border-gray-800">
          <h2 id="audience-dialog-title" class="text-lg font-bold">{{ t("postsFeed.audience.title") }}</h2>
          <button type="button" class="icon-btn absolute end-2 top-1/2 -translate-y-1/2" :aria-label="t('postsFeed.why.close')" @click="emit('close')">
            <X class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <div class="p-3" role="radiogroup" :aria-label="t('feed.audience')">
          <button
            v-for="a in AUDIENCES"
            :key="a.v"
            type="button"
            role="radio"
            :aria-checked="audience === a.v"
            class="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-start transition hover:bg-gray-100 disabled:opacity-60 dark:hover:bg-gray-800"
            :class="audience === a.v ? 'bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-200' : ''"
            :disabled="busy"
            @click="pick(a.v)"
          >
            <span class="flex h-10 w-10 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800">
              <component :is="a.icon" class="h-5 w-5" aria-hidden="true" />
            </span>
            <span class="flex-1 text-sm font-semibold">{{ t(a.label) }}</span>
            <Check v-if="audience === a.v" class="h-5 w-5" aria-hidden="true" />
          </button>
          <p v-if="error" class="mt-2 px-1 text-sm text-red-600 dark:text-red-400" role="alert">{{ error }}</p>
        </div>
      </div>
    </div>
  </Teleport>
</template>
