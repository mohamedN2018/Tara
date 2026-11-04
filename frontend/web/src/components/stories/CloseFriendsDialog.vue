<script setup lang="ts">
import { Search, Star } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { graphService } from "@/services/graph";
import { STORY_ERRORS, storiesService } from "@/services/stories";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

import StoryDialog from "./StoryDialog.vue";

// My close friends list (stories with the close friends audience reach only
// them). Candidates are my friends; the server refuses anyone else and drops a
// person from the list when we stop being friends or one blocks the other.
withDefaults(defineProps<{ inline?: boolean }>(), { inline: false });
const emit = defineEmits<{ close: []; changed: [count: number] }>();

const { t } = useI18n();
const toasts = useToastStore();
const directory = useDirectoryStore();

const loading = ref(true);
const failed = ref(false);
const friends = ref<string[]>([]);
const onList = ref<Set<string>>(new Set());
const busy = ref<Set<string>>(new Set());
const query = ref("");

async function load() {
  loading.value = true;
  failed.value = false;
  try {
    const [ids, list] = await Promise.all([graphService.friends(), storiesService.allCloseFriends()]);
    friends.value = ids;
    onList.value = new Set(list.map((c) => c.account_id));
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const matches = (id: string) => {
  const q = query.value.trim().toLocaleLowerCase();
  return !q || directory.label(id).toLocaleLowerCase().includes(q);
};
// People still listed but no longer in my friends list are shown too, so they can be removed.
const listed = computed(() => [...onList.value].filter(matches));
const others = computed(() => friends.value.filter((id) => !onList.value.has(id) && matches(id)));

async function toggle(id: string) {
  if (busy.value.has(id)) return;
  busy.value = new Set(busy.value).add(id);
  const adding = !onList.value.has(id);
  try {
    if (adding) await storiesService.addCloseFriends([id]);
    else await storiesService.removeCloseFriend(id);
    const next = new Set(onList.value);
    if (adding) next.add(id);
    else next.delete(id);
    onList.value = next;
    toasts.success(t(adding ? "stories.closeFriends.added" : "stories.closeFriends.removed"));
    emit("changed", next.size);
  } catch (e) {
    toasts.error(e, STORY_ERRORS);
  } finally {
    const rest = new Set(busy.value);
    rest.delete(id);
    busy.value = rest;
  }
}
</script>

<template>
  <StoryDialog :inline="inline" :title="t('stories.closeFriends.title')" :close-label="t('stories.closeFriends.close')" @close="emit('close')">
    <div class="flex min-h-0 flex-col gap-3" data-testid="close-friends-dialog">
      <p class="text-sm text-gray-600 dark:text-gray-300">{{ t("stories.closeFriends.subtitle") }}</p>
      <label class="relative block">
        <span class="sr-only">{{ t("stories.closeFriends.search") }}</span>
        <Search class="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden="true" />
        <input v-model="query" type="search" class="input ps-9" :placeholder="t('stories.closeFriends.search')" />
      </label>

      <LoadingSkeleton v-if="loading" :rows="2" />
      <ErrorState v-else-if="failed" @retry="load" />
      <div v-else class="-mx-1 min-h-0 flex-1 space-y-4 overflow-y-auto px-1">
        <section>
          <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
            {{ t("stories.closeFriends.onList", { n: onList.size }) }}
          </h3>
          <p v-if="!onList.size" class="py-2 text-sm text-gray-500 dark:text-gray-400">{{ t("stories.closeFriends.empty") }}</p>
          <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800">
            <li v-for="id in listed" :key="id" class="flex items-center gap-3 py-2" data-testid="close-friend-row">
              <span class="relative">
                <UserAvatar :name="directory.label(id)" :media-id="directory.avatarOf(id)" :size="40" />
                <Star class="absolute -bottom-0.5 -end-0.5 h-4 w-4 rounded-full bg-emerald-500 p-0.5 text-white" fill="currentColor" aria-hidden="true" />
              </span>
              <span dir="auto" class="min-w-0 flex-1 truncate text-sm font-semibold">{{ directory.label(id) }}</span>
              <button type="button" class="btn-outline px-3 py-1.5" :disabled="busy.has(id)" @click="toggle(id)">
                {{ t("stories.closeFriends.remove") }}
              </button>
            </li>
          </ul>
        </section>

        <section>
          <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
            {{ t("stories.closeFriends.others") }}
          </h3>
          <p v-if="!friends.length" class="py-2 text-sm text-gray-500 dark:text-gray-400">{{ t("stories.closeFriends.noFriends") }}</p>
          <p v-else-if="!others.length && query" class="py-2 text-sm text-gray-500 dark:text-gray-400">{{ t("stories.closeFriends.noMatch") }}</p>
          <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800">
            <li v-for="id in others" :key="id" class="flex items-center gap-3 py-2" data-testid="close-friend-candidate">
              <UserAvatar :name="directory.label(id)" :media-id="directory.avatarOf(id)" :size="40" />
              <span dir="auto" class="min-w-0 flex-1 truncate text-sm font-semibold">{{ directory.label(id) }}</span>
              <button type="button" class="btn-soft px-3 py-1.5" :disabled="busy.has(id)" @click="toggle(id)">
                {{ t("stories.closeFriends.add") }}
              </button>
            </li>
          </ul>
        </section>
      </div>
    </div>
  </StoryDialog>
</template>
