<script setup lang="ts">
import { LayoutGrid, List, SlidersHorizontal, X } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import type { ProfileState } from "@/lib/useProfile";

export type PostsView = "list" | "grid";

// The profile's "Posts" header (plan 08): Filters (the year and who posted,
// sent to the post service as `year` / `tagged_id`) and the List / Grid switch.
const props = defineProps<{ state: ProfileState; view: PostsView }>();
const emit = defineEmits<{ "update:view": [view: PostsView] }>();
const { t } = useI18n();

const open = ref(false);
const year = ref<number | null>(null);
const postedBy = ref<"author" | "others">("author");
watch(open, (on) => {
  if (!on) return;
  year.value = props.state.postFilters.year ?? null;
  postedBy.value = props.state.postFilters.postedBy === "others" ? "others" : "author";
});

// Years from now back to when the person joined (ten years when that is unknown).
const years = computed(() => {
  const now = new Date().getFullYear();
  const joined = props.state.profile?.created_at ? new Date(props.state.profile.created_at).getFullYear() : now - 9;
  const from = Number.isFinite(joined) ? Math.min(joined, now) : now - 9;
  return Array.from({ length: now - from + 1 }, (_, i) => now - i);
});
const selfName = computed(() => (props.state.isSelf ? t("post.you") : props.state.displayName));

function apply() {
  props.state.setPostFilters({ year: year.value, postedBy: postedBy.value });
  open.value = false;
}
function clear() {
  props.state.setPostFilters({});
  open.value = false;
}

const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
useEscapeKey(open, () => (open.value = false));
const seg = (on: boolean) =>
  [
    "inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-sm font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400",
    on ? "bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-200" : "text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800",
  ].join(" ");
</script>

<template>
  <div class="card px-4 py-3" data-testid="profile-posts-header">
    <div class="flex flex-wrap items-center gap-2">
      <h2 class="me-auto text-xl font-bold">{{ t("people.posts.title") }}</h2>
      <button
        type="button"
        class="btn-soft px-3 py-2"
        aria-haspopup="dialog"
        :aria-expanded="open"
        data-testid="profile-posts-filters"
        @click="open = true"
      >
        <SlidersHorizontal class="h-4 w-4" aria-hidden="true" />
        {{ state.activeFilterCount ? t("profileTools.posts.filtersOn", { n: state.activeFilterCount }) : t("profileTools.posts.filters") }}
      </button>
    </div>
    <div class="mt-3 flex items-center gap-1 border-t border-gray-200 pt-2 dark:border-gray-800" role="radiogroup" :aria-label="t('profileTools.posts.view')">
      <button
        type="button"
        role="radio"
        :aria-checked="view === 'list'"
        :class="seg(view === 'list')"
        class="flex-1 justify-center"
        data-testid="profile-posts-view-list"
        @click="emit('update:view', 'list')"
      >
        <List class="h-4 w-4" aria-hidden="true" /> {{ t("profileTools.posts.list") }}
      </button>
      <button
        type="button"
        role="radio"
        :aria-checked="view === 'grid'"
        :class="seg(view === 'grid')"
        class="flex-1 justify-center"
        data-testid="profile-posts-view-grid"
        @click="emit('update:view', 'grid')"
      >
        <LayoutGrid class="h-4 w-4" aria-hidden="true" /> {{ t("profileTools.posts.grid") }}
      </button>
    </div>

    <Teleport to="body">
      <div v-if="open" class="fixed inset-0 z-[75] flex items-end justify-center bg-gray-950/60 backdrop-blur-sm sm:items-center sm:p-4">
        <div class="fixed inset-0" @click="open = false" />
        <div
          ref="dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="post-filters-title"
          tabindex="-1"
          class="card relative z-10 w-full rounded-b-none p-4 shadow-pop sm:max-w-md sm:rounded-2xl sm:p-5"
          data-testid="profile-posts-filters-dialog"
        >
          <div class="mb-4 flex items-center justify-between gap-2">
            <h2 id="post-filters-title" class="text-lg font-bold">{{ t("profileTools.posts.filtersTitle") }}</h2>
            <button type="button" class="icon-btn h-9 w-9" :aria-label="t('profileTools.posts.close')" @click="open = false">
              <X class="h-5 w-5" aria-hidden="true" />
            </button>
          </div>

          <label class="block text-sm font-semibold" for="post-filter-year">{{ t("profileTools.posts.year") }}</label>
          <select id="post-filter-year" v-model="year" class="input mt-1 w-full" data-testid="profile-posts-filter-year">
            <option :value="null">{{ t("profileTools.posts.anyYear") }}</option>
            <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
          </select>

          <fieldset class="mt-4">
            <legend class="text-sm font-semibold">{{ t("profileTools.posts.postedBy") }}</legend>
            <label class="mt-2 flex items-center gap-2 text-sm">
              <input v-model="postedBy" type="radio" value="author" class="accent-brand-600" data-testid="profile-posts-filter-author" />
              <bdi>{{ t("profileTools.posts.postedBySelf", { name: selfName }) }}</bdi>
            </label>
            <label class="mt-2 flex items-start gap-2 text-sm">
              <input v-model="postedBy" type="radio" value="others" class="mt-0.5 accent-brand-600" data-testid="profile-posts-filter-others" />
              <span>
                {{ t("profileTools.posts.postedByOthers") }}
                <span class="block text-xs text-gray-600 dark:text-gray-400">{{ t("profileTools.posts.othersHint", { name: state.displayName }) }}</span>
              </span>
            </label>
          </fieldset>

          <div class="mt-5 flex justify-end gap-2">
            <button type="button" class="btn-ghost" data-testid="profile-posts-filter-clear" @click="clear">{{ t("profileTools.posts.clear") }}</button>
            <button type="button" class="btn-primary" data-testid="profile-posts-filter-apply" @click="apply">{{ t("profileTools.posts.apply") }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
