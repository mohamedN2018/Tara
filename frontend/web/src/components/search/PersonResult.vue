<script setup lang="ts">
import { Check, Clock, MapPin, UserPlus, Users } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { canFollow, personAction } from "@/lib/search";
import { graphService } from "@/services/graph";
import type { Relationship, SearchResult } from "@/services/search";
import { useToastStore } from "@/stores/toasts";

const props = defineProps<{ result: SearchResult }>();
const { t } = useI18n();
const toasts = useToastStore();

const rel = ref<Relationship | null>(props.result.relationship ?? null);
watch(() => props.result.relationship, (v) => (rel.value = v ?? null));
const busy = ref(false);

const name = computed(() => props.result.display_name || props.result.title || props.result.handle || "");
const action = computed(() => personAction(rel.value));
const followable = computed(() => canFollow(rel.value));
const mutual = computed(() => props.result.mutual_count ?? 0);

async function run(fn: () => Promise<unknown>, next: Partial<Relationship>) {
  if (busy.value || !rel.value) return;
  busy.value = true;
  try {
    await fn();
    rel.value = { ...rel.value, ...next };
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

const addFriend = () => run(async () => void (await graphService.sendFriendRequest(props.result.id)), { state: "pending_out" });
const confirm = () =>
  run(() => graphService.acceptFriendRequest(rel.value?.request_id ?? ""), { state: "friends", request_id: null });
const toggleFollow = () =>
  rel.value?.following
    ? run(() => graphService.unfollow(props.result.id), { following: false })
    : run(() => graphService.follow(props.result.id), { following: true });
</script>

<template>
  <article class="card flex items-center gap-3 p-3 sm:p-4" data-testid="person-result">
    <RouterLink :to="{ name: 'profile-by-id', params: { id: result.id } }" class="shrink-0 rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400" tabindex="-1" aria-hidden="true">
      <UserAvatar :name="name" :media-id="result.avatar_media_id" :size="56" />
    </RouterLink>
    <div class="min-w-0 flex-1">
      <RouterLink
        :to="{ name: 'profile-by-id', params: { id: result.id } }"
        class="block truncate font-semibold hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400"
        dir="auto"
      >
        {{ name }}
      </RouterLink>
      <p v-if="result.handle" class="truncate text-xs text-gray-500 dark:text-gray-400" dir="ltr">@{{ result.handle }}</p>
      <p v-if="result.city" class="mt-0.5 flex items-center gap-1 truncate text-xs text-gray-500 dark:text-gray-400">
        <MapPin class="h-3 w-3 shrink-0" aria-hidden="true" />
        <span class="truncate" dir="auto">{{ result.city }}</span>
      </p>
      <p v-if="mutual > 0" class="mt-0.5 flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
        <Users class="h-3 w-3 shrink-0" aria-hidden="true" />
        {{ t("search.mutual", mutual) }}
      </p>
    </div>

    <div class="flex shrink-0 flex-col items-stretch gap-1.5 sm:flex-row sm:items-center">
      <button v-if="action === 'add'" type="button" class="btn-soft px-3 py-1.5" :disabled="busy" @click="addFriend">
        <UserPlus class="h-4 w-4" aria-hidden="true" />
        <span>{{ t("search.addFriend") }}</span>
      </button>
      <button v-else-if="action === 'requested'" type="button" class="btn-ghost px-3 py-1.5" disabled>
        <Clock class="h-4 w-4" aria-hidden="true" />
        <span>{{ t("search.requested") }}</span>
      </button>
      <button v-else-if="action === 'confirm'" type="button" class="btn-primary px-3 py-1.5" :disabled="busy" @click="confirm">
        <Check class="h-4 w-4" aria-hidden="true" />
        <span>{{ t("search.confirm") }}</span>
      </button>
      <span v-else-if="action === 'friends'" class="inline-flex items-center gap-1 rounded-xl bg-gray-100 px-3 py-1.5 text-sm font-semibold text-gray-700 dark:bg-gray-800 dark:text-gray-200">
        <Users class="h-4 w-4" aria-hidden="true" />
        {{ t("search.friends") }}
      </span>
      <button
        v-if="followable"
        type="button"
        class="btn-outline px-3 py-1.5"
        :aria-pressed="!!rel?.following"
        :aria-label="rel?.following ? t('search.unfollow', { name }) : t('search.followName', { name })"
        :disabled="busy"
        @click="toggleFollow"
      >
        {{ rel?.following ? t("search.following") : t("search.follow") }}
      </button>
    </div>
  </article>
</template>
