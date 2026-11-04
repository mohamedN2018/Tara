<script setup lang="ts">
import { MapPin } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { type ComposerPost, composerService, FEELING_EMOJI } from "@/services/composer";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";
import type { Post } from "@/types";

// The line under a post's author (2C): "feeling happy · with Sara and 2 others ·
// at Cairo". The server leaves out tagged people blocked either way with the
// viewer. A tagged viewer can take their own tag off.
const props = defineProps<{ post: Post }>();

const { t, te } = useI18n();
const auth = useAuthStore();
const directory = useDirectoryStore();
const toasts = useToastStore();

const extra = computed(() => props.post as ComposerPost);
const removed = ref(false);
const tagged = computed(() => (removed.value ? (extra.value.tagged_ids ?? []).filter((id) => id !== auth.account?.id) : (extra.value.tagged_ids ?? [])));
const feelingKey = computed(() => {
  const key = extra.value.feeling ?? "";
  return key && te(`composer.feelings.${key}`) ? key : "";
});
const place = computed(() => (extra.value.location ?? "").trim());
const iAmTagged = computed(() => !!auth.account?.id && tagged.value.includes(auth.account.id));
const shown = computed(() => !!feelingKey.value || tagged.value.length > 0 || !!place.value);

async function removeMyTag() {
  try {
    await composerService.removeMyTag(props.post.id);
    removed.value = true;
    toasts.success(t("composer.meta.tagRemoved"));
  } catch (err) {
    toasts.error(err);
  }
}
</script>

<template>
  <p v-if="shown" class="flex flex-wrap items-center gap-x-1 text-[13px] text-gray-600 dark:text-gray-300" data-testid="post-composer-meta">
    <span v-if="feelingKey">
      <span aria-hidden="true">{{ FEELING_EMOJI[feelingKey] }}</span> {{ t(`composer.feelings.${feelingKey}`) }}
    </span>
    <span v-if="tagged.length">
      <i18n-t :keypath="tagged.length > 1 ? 'composer.meta.withOthers' : 'composer.meta.with'" :plural="tagged.length - 1" scope="global">
        <template #name>
          <RouterLink :to="{ name: 'profile-by-id', params: { id: tagged[0] } }" class="font-semibold text-gray-900 hover:underline dark:text-white" dir="auto">{{ directory.label(tagged[0]) }}</RouterLink>
        </template>
        <template #count>{{ tagged.length - 1 }}</template>
      </i18n-t>
    </span>
    <span v-if="place" class="inline-flex items-center gap-0.5">
      <MapPin class="h-3 w-3" aria-hidden="true" />
      <span dir="auto">{{ t("composer.meta.at", { place }) }}</span>
    </span>
    <button v-if="iAmTagged" type="button" class="ms-1 text-xs font-semibold text-brand-700 hover:underline dark:text-brand-300" @click="removeMyTag">
      {{ t("composer.meta.removeMyTag") }}
    </button>
  </p>
</template>
