<script setup lang="ts">
// One person (or one shared screen) in the call grid. The track is attached to
// this tile's own <video> and detached when the tile or its track goes away.
import { MicOff, MonitorUp } from "lucide-vue-next";
import { onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import type { CallTile } from "@/stores/calls";
import { useDirectoryStore } from "@/stores/directory";

const props = defineProps<{ tile: CallTile; large?: boolean }>();
const { t } = useI18n();
const directory = useDirectoryStore();
const video = ref<HTMLVideoElement | null>(null);

let attached: CallTile["video"] = null;

function detach() {
  if (attached && video.value) attached.detach(video.value);
  attached = null;
}

watch(
  [() => props.tile.video, video],
  ([track, el]) => {
    if (attached === track && el) return;
    detach();
    if (track && el) {
      track.attach(el);
      attached = track;
    }
  },
  { immediate: true, flush: "post" },
);

onBeforeUnmount(detach);

const name = () => (props.tile.local ? t("calls.you") : directory.label(props.tile.identity));
</script>

<template>
  <figure
    class="relative flex min-h-0 items-center justify-center overflow-hidden rounded-2xl bg-gray-900"
    :class="[tile.speaking && !tile.screen ? 'ring-2 ring-brand-400' : '', large ? 'h-full w-full' : 'aspect-video w-full']"
    :data-testid="tile.local ? 'call-tile-local' : 'call-tile-remote'"
  >
    <video
      v-show="tile.video"
      ref="video"
      autoplay
      playsinline
      muted
      class="h-full w-full"
      :class="[tile.screen ? 'object-contain' : 'object-cover', tile.local && !tile.screen ? '-scale-x-100' : '']"
    />
    <UserAvatar v-if="!tile.video" :name="name()" :media-id="tile.local ? null : directory.avatarOf(tile.identity)" :size="large ? 96 : 56" />
    <figcaption class="absolute bottom-2 start-2 flex max-w-[80%] items-center gap-1 rounded-full bg-gray-950/60 px-2 py-0.5 text-xs text-white">
      <MonitorUp v-if="tile.screen" class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <MicOff v-else-if="tile.micMuted" class="h-3.5 w-3.5 shrink-0" :aria-label="t('calls.muted')" />
      <span class="truncate" dir="auto">{{ tile.screen ? t("calls.screenOf", { name: name() }) : name() }}</span>
    </figcaption>
  </figure>
</template>
