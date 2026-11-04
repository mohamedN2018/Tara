<script setup lang="ts">
import { Bookmark, Check, FolderPlus, X } from "lucide-vue-next";
import { nextTick, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { postService, type SavedCollection } from "@/services/post";
import { useToastStore } from "@/stores/toasts";

/**
 * "Save to collection" (post menu) and "Move to collection" (Saved page): the
 * owner's collections as radio rows, plus "Create new collection". With
 * `savedId` the saved item moves (PATCH /saved/<id>/); otherwise the post is
 * saved into the picked collection (POST /posts/<id>/save/).
 */
const props = withDefaults(
  defineProps<{ postId: string; savedId?: string | null; currentId?: string | null }>(),
  { savedId: null, currentId: null },
);
const emit = defineEmits<{ close: []; done: [collection: SavedCollection] }>();

const { t } = useI18n();
const toasts = useToastStore();
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
useEscapeKey(ref(true), () => emit("close"));

const collections = ref<SavedCollection[]>([]);
const loading = ref(true);
const busy = ref(false);
const creating = ref(false);
const name = ref("");
const nameInput = ref<HTMLInputElement | null>(null);

const label = (c: SavedCollection) => (c.is_default ? t("postsFeed.saved.defaultName") : c.name);

async function load() {
  loading.value = true;
  try {
    collections.value = await postService.collections();
  } catch (e) {
    toasts.error(e);
  } finally {
    loading.value = false;
  }
}

async function pick(c: SavedCollection) {
  if (busy.value) return;
  busy.value = true;
  try {
    if (props.savedId) await postService.moveSaved(props.savedId, c.is_default ? null : c.id);
    else await postService.save(props.postId, c.id);
    toasts.success(t(props.savedId ? "postsFeed.saved.moved" : "postsFeed.saved.savedTo", { name: label(c) }));
    emit("done", c);
    emit("close");
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

async function startCreate() {
  creating.value = true;
  await nextTick();
  nameInput.value?.focus();
}

async function create() {
  const value = name.value.trim();
  if (!value || busy.value) return;
  busy.value = true;
  try {
    const c = await postService.createCollection(value);
    collections.value = [...collections.value, c];
    name.value = "";
    creating.value = false;
    toasts.success(t("postsFeed.saved.created", { name: c.name }));
    busy.value = false;
    await pick(c);
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[60] flex items-end justify-center bg-gray-950/60 backdrop-blur-sm sm:items-center sm:p-4">
      <div class="fixed inset-0" aria-hidden="true" @click="emit('close')" />
      <div
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="save-to-title"
        tabindex="-1"
        class="card relative z-10 flex max-h-[80vh] w-full animate-pop-in flex-col rounded-b-none rounded-t-2xl p-0 shadow-pop sm:max-w-sm sm:rounded-2xl"
        data-testid="save-to-collection"
      >
        <div class="relative flex items-center justify-center border-b border-gray-100 px-12 py-3 dark:border-gray-800">
          <h2 id="save-to-title" class="truncate text-lg font-bold">
            {{ savedId ? t("postsFeed.saved.moveTitle") : t("postsFeed.saved.addTitle") }}
          </h2>
          <button type="button" class="icon-btn absolute end-2 top-1/2 -translate-y-1/2" :aria-label="t('postsFeed.saved.close')" @click="emit('close')">
            <X class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto p-2" role="radiogroup" :aria-label="t('postsFeed.saved.collections')">
          <p v-if="loading" class="px-3 py-3 text-sm text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
          <button
            v-for="c in collections"
            :key="c.id"
            type="button"
            role="radio"
            :aria-checked="currentId === c.id"
            class="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-start transition hover:bg-gray-100 disabled:opacity-60 dark:hover:bg-gray-800"
            :disabled="busy"
            @click="pick(c)"
          >
            <span class="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600 dark:bg-brand-950/60 dark:text-brand-300">
              <Bookmark class="h-5 w-5" aria-hidden="true" />
            </span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-semibold" dir="auto">{{ label(c) }}</span>
              <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t("postsFeed.saved.items", { n: c.item_count }, c.item_count) }}</span>
            </span>
            <Check v-if="currentId === c.id" class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" />
          </button>
        </div>

        <div class="border-t border-gray-100 p-3 dark:border-gray-800">
          <form v-if="creating" class="space-y-2" @submit.prevent="create">
            <label for="save-to-name" class="label">{{ t("postsFeed.saved.name") }}</label>
            <input
              id="save-to-name"
              ref="nameInput"
              v-model="name"
              class="input"
              dir="auto"
              maxlength="80"
              :placeholder="t('postsFeed.saved.namePlaceholder')"
              data-testid="collection-name"
            />
            <div class="flex justify-end gap-2">
              <button type="button" class="btn-ghost" @click="creating = false">{{ t("postsFeed.saved.cancel") }}</button>
              <button type="submit" class="btn-primary" :disabled="busy || !name.trim()">{{ t("postsFeed.saved.createButton") }}</button>
            </div>
          </form>
          <button v-else type="button" class="btn-ghost w-full justify-start" data-testid="collection-create" @click="startCreate">
            <FolderPlus class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" />
            {{ t("postsFeed.saved.create") }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
