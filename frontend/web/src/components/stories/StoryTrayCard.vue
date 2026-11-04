<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { useMediaUrl } from "@/lib/useMediaUrl";
import { backgroundStyle, type StoryGroup } from "@/services/stories";
import { useDirectoryStore } from "@/stores/directory";

// One author in the stories rail: the cover is the first story they haven't
// seen (or their latest), their avatar sits in a ring that is brand-coloured
// while something is unseen, and the name runs along the bottom.
const props = defineProps<{ group: StoryGroup; mine?: boolean }>();
defineEmits<{ open: [] }>();

const { t } = useI18n();
const directory = useDirectoryStore();

const cover = computed(() => {
  const list = props.group.stories;
  return list.find((s) => !s.seen) ?? list[list.length - 1];
});
const photo = useMediaUrl(() => (cover.value?.kind === "photo" ? cover.value.media_id : null));
const name = computed(() => (props.mine ? t("stories.rail.yourStory") : directory.label(props.group.author_id)));
const fullName = computed(() => directory.label(props.group.author_id));
</script>

<template>
  <button
    type="button"
    class="group relative h-[208px] w-[128px] shrink-0 overflow-hidden rounded-xl bg-gray-900 text-start shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-gray-950"
    :aria-label="t('stories.rail.open', { name: fullName })"
    data-testid="story-tray-card"
    :data-author="group.author_id"
    @click="$emit('open')"
  >
    <img
      v-if="photo"
      :src="photo"
      alt=""
      class="absolute inset-0 h-full w-full object-cover transition duration-300 group-hover:scale-105"
      loading="lazy"
      decoding="async"
    />
    <div
      v-else
      class="absolute inset-0 flex items-center justify-center p-3 transition duration-300 group-hover:scale-105"
      :style="{ backgroundImage: backgroundStyle(cover?.background) }"
    >
      <p v-if="cover?.kind === 'text'" dir="auto" class="line-clamp-5 text-center text-xs font-bold leading-snug text-white">
        {{ cover.text }}
      </p>
    </div>
    <span class="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/30 via-transparent to-black/70" />
    <span
      class="absolute start-2 top-2 rounded-full p-[3px]"
      :class="group.has_unseen ? 'bg-gradient-to-br from-brand-600 via-brand-400 to-accent-500' : 'bg-white/70 dark:bg-gray-500'"
    >
      <UserAvatar
        :name="fullName"
        :media-id="directory.avatarOf(group.author_id)"
        :size="34"
        class="ring-2 ring-gray-900"
      />
    </span>
    <span v-if="group.has_unseen" class="sr-only">{{ t("stories.rail.unseen") }}</span>
    <span dir="auto" class="absolute inset-x-2 bottom-2 line-clamp-2 text-[13px] font-semibold leading-tight text-white drop-shadow">
      {{ name }}
    </span>
  </button>
</template>
