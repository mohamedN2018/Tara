<script setup lang="ts">
// The call UI, mounted once in the app shell: the incoming-call sheet, the
// outgoing/connecting screen, the in-call view (grid with spotlight, controls)
// and a minimised pill. Escape minimises; it never hangs up.
import {
  ChevronDown,
  Maximize2,
  Mic,
  MicOff,
  MonitorUp,
  Phone,
  PhoneOff,
  SwitchCamera,
  Video,
  VideoOff,
  Volume2,
  X,
} from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import CallAudio from "@/components/calls/CallAudio.vue";
import CallTile from "@/components/calls/CallTile.vue";
import UserAvatar from "@/components/common/UserAvatar.vue";
import { formatDuration } from "@/lib/callLog";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { useAuthStore } from "@/stores/auth";
import { useCallStore } from "@/stores/calls";
import { useDirectoryStore } from "@/stores/directory";

const { t, locale } = useI18n();
const calls = useCallStore();
const auth = useAuthStore();
const directory = useDirectoryStore();

const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);

const me = computed(() => auth.account?.id ?? "");
const showIncoming = computed(() => calls.phase === "incoming" && !!calls.incoming);
const showMain = computed(
  () => !calls.minimised && ["outgoing", "connecting", "in_call", "ended"].includes(calls.phase),
);
const showPill = computed(() => calls.minimised && ["outgoing", "connecting", "in_call"].includes(calls.phase));

/** Everyone in the call but me (from the server's list), for names and avatars. */
const others = computed(() =>
  (calls.call?.participants ?? []).map((p) => p.account_id).filter((id) => id !== me.value),
);
const peerId = computed(() => (calls.incoming ? calls.incoming.initiator : others.value[0] ?? ""));
const title = computed(() => {
  if (calls.incoming) return directory.label(calls.incoming.initiator);
  const names = others.value.slice(0, 3).map((id) => directory.label(id));
  const rest = others.value.length - names.length;
  const list = listOf(names);
  return rest > 0 ? t("calls.namesAndOthers", { names: list, count: rest }, rest) : list;
});
function listOf(names: string[]): string {
  try {
    return new Intl.ListFormat(locale.value, { style: "short", type: "unit" }).format(names);
  } catch {
    return names.join(", ");
  }
}
const kindLabel = computed(() => (calls.kind === "video" ? t("calls.video") : t("calls.voice")));

const status = computed(() => {
  if (calls.phase === "ended") return t(`calls.end.${calls.endReason ?? "ended"}`);
  if (calls.reconnecting) return t("calls.reconnecting");
  if (calls.phase === "outgoing") return t("calls.ringing");
  if (calls.phase === "connecting") return t("calls.connecting");
  if (calls.phase === "in_call") return formatDuration(calls.duration);
  return "";
});
const inRoom = computed(() => calls.tiles.filter((tile) => !tile.screen).length);
const hasVideo = computed(() => calls.tiles.some((tile) => tile.video));
const useGrid = computed(() => calls.isGroup || hasVideo.value || calls.kind === "video");
const gridCols = computed(() => {
  const n = calls.visibleTiles.length;
  if (n <= 1) return "grid-cols-1";
  if (n <= 4) return "grid-cols-1 sm:grid-cols-2";
  return "grid-cols-2 sm:grid-cols-3";
});
const strip = computed(() =>
  calls.spotlight ? calls.visibleTiles.filter((tile) => tile.key !== calls.spotlight?.key) : [],
);

function onEscape(event: KeyboardEvent) {
  // Escape never hangs up; during a call it tucks the view away.
  if (calls.phase === "incoming" || calls.phase === "ended") return;
  event.stopPropagation();
  calls.minimised = true;
}

const CONTROL =
  "flex h-12 w-12 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-300";
</script>

<template>
  <Teleport to="body">
    <!-- Everyone is heard, whether or not their tile fits the grid. -->
    <CallAudio v-for="a in calls.remoteAudio" :key="a.key" :track="a.track" />

    <!-- Incoming call -->
    <div v-if="showIncoming" class="fixed inset-0 z-[70] flex items-end justify-center bg-gray-950/50 p-4 sm:items-center">
      <section
        ref="dialog"
        role="alertdialog"
        aria-modal="true"
        :aria-label="t(calls.kind === 'video' ? 'calls.incomingVideo' : 'calls.incomingVoice')"
        aria-describedby="call-incoming-caller"
        tabindex="-1"
        class="card w-full max-w-sm p-6 text-center"
        data-testid="call-incoming"
        @keydown.esc.prevent
      >
        <div class="mx-auto mb-3 w-fit animate-pulse rounded-full ring-4 ring-brand-400/40">
          <UserAvatar :name="title" :media-id="directory.avatarOf(peerId)" :size="80" />
        </div>
        <p id="call-incoming-caller" class="truncate text-lg font-bold" dir="auto">{{ title }}</p>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          {{ t(calls.kind === "video" ? "calls.incomingVideo" : "calls.incomingVoice") }}
          <template v-if="calls.isGroup"> · {{ t("calls.groupCall") }}</template>
        </p>
        <div class="mt-6 flex items-center justify-center gap-10">
          <div class="flex flex-col items-center gap-1">
            <button
              type="button"
              class="flex h-14 w-14 items-center justify-center rounded-full bg-red-600 text-white hover:bg-red-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-400"
              :aria-label="t('calls.decline')"
              data-testid="call-decline"
              @click="calls.decline()"
            >
              <PhoneOff class="h-6 w-6" aria-hidden="true" />
            </button>
            <span class="text-xs">{{ t("calls.decline") }}</span>
          </div>
          <div class="flex flex-col items-center gap-1">
            <button
              type="button"
              class="flex h-14 w-14 items-center justify-center rounded-full bg-green-600 text-white hover:bg-green-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-green-400"
              :aria-label="t('calls.accept')"
              data-testid="call-accept"
              @click="calls.accept()"
            >
              <Video v-if="calls.kind === 'video'" class="h-6 w-6" aria-hidden="true" />
              <Phone v-else class="h-6 w-6" aria-hidden="true" />
            </button>
            <span class="text-xs">{{ t("calls.accept") }}</span>
          </div>
        </div>
      </section>
    </div>

    <!-- Outgoing, connecting, in call, ended -->
    <section
      v-else-if="showMain"
      ref="dialog"
      role="dialog"
      aria-modal="true"
      :aria-label="t('calls.dialogLabel', { kind: kindLabel })"
      tabindex="-1"
      class="fixed inset-0 z-[70] flex flex-col bg-gray-950 text-white"
      data-testid="call-overlay"
      :data-phase="calls.phase"
      @keydown.esc="onEscape"
    >
      <header class="flex items-center gap-3 px-4 pb-2 pt-4">
        <div class="min-w-0 flex-1">
          <p class="truncate font-semibold" dir="auto">{{ title || kindLabel }}</p>
          <p class="text-sm text-gray-300" role="status" aria-live="polite" data-testid="call-status">
            <span v-if="calls.phase === 'in_call'" data-testid="call-in-progress">{{ status }}</span>
            <template v-else>{{ status }}</template>
            <template v-if="calls.isGroup && calls.phase === 'in_call'"> · {{ t("calls.inCallCount", { count: inRoom }, inRoom) }}</template>
          </p>
        </div>
        <button
          v-if="calls.phase !== 'ended'"
          type="button"
          :class="CONTROL"
          class="h-10 w-10"
          :aria-label="t('calls.minimise')"
          @click="calls.minimised = true"
        >
          <ChevronDown class="h-5 w-5" aria-hidden="true" />
        </button>
        <button
          v-else
          type="button"
          :class="CONTROL"
          class="h-10 w-10"
          :aria-label="t('calls.close')"
          data-testid="call-close"
          @click="calls.dismiss()"
        >
          <X class="h-5 w-5" aria-hidden="true" />
        </button>
      </header>

      <p v-if="calls.notice" class="mx-4 rounded-xl bg-brand-500/20 px-3 py-2 text-sm text-brand-100" role="alert" data-testid="call-notice">
        {{ t(calls.notice) }}
      </p>
      <button
        v-if="calls.audioBlocked"
        type="button"
        class="mx-auto mt-2 rounded-full bg-brand-600 px-4 py-1.5 text-sm font-medium hover:bg-brand-700"
        @click="calls.enableAudio()"
      >
        <Volume2 class="me-1 inline h-4 w-4" aria-hidden="true" />{{ t("calls.enableAudio") }}
      </button>

      <!-- Stage -->
      <div class="min-h-0 flex-1 p-3">
        <div v-if="!useGrid || !calls.tiles.length" class="flex h-full flex-col items-center justify-center gap-4">
          <div :class="calls.phase === 'outgoing' ? 'animate-pulse' : ''" class="rounded-full ring-4 ring-brand-500/30">
            <UserAvatar :name="title || kindLabel" :media-id="directory.avatarOf(peerId)" :size="112" />
          </div>
        </div>
        <div v-else-if="calls.spotlight" class="flex h-full flex-col gap-2 lg:flex-row">
          <div class="min-h-0 flex-1">
            <CallTile :tile="calls.spotlight" large />
          </div>
          <div v-if="strip.length" class="flex shrink-0 gap-2 overflow-x-auto lg:w-56 lg:flex-col lg:overflow-y-auto">
            <div v-for="tile in strip" :key="tile.key" class="w-40 shrink-0 lg:w-full">
              <CallTile :tile="tile" />
            </div>
          </div>
        </div>
        <div v-else class="grid h-full content-center gap-2 overflow-y-auto" :class="gridCols">
          <CallTile v-for="tile in calls.visibleTiles" :key="tile.key" :tile="tile" />
        </div>
      </div>

      <!-- Controls -->
      <footer v-if="calls.phase !== 'ended'" class="flex flex-wrap items-center justify-center gap-3 px-4 pb-6 pt-2" role="toolbar" :aria-label="t('calls.controls')">
        <button
          type="button"
          :class="[CONTROL, !calls.micOn ? 'bg-white text-gray-900 hover:bg-gray-200' : '']"
          :aria-label="calls.micOn ? t('calls.mute') : t('calls.unmute')"
          :aria-pressed="!calls.micOn"
          data-testid="call-toggle-mic"
          @click="calls.toggleMic()"
        >
          <Mic v-if="calls.micOn" class="h-5 w-5" aria-hidden="true" />
          <MicOff v-else class="h-5 w-5" aria-hidden="true" />
        </button>
        <button
          type="button"
          :class="[CONTROL, calls.camOn ? 'bg-white text-gray-900 hover:bg-gray-200' : '']"
          :aria-label="calls.camOn ? t('calls.cameraOff') : t('calls.cameraOn')"
          :aria-pressed="calls.camOn"
          data-testid="call-toggle-camera"
          @click="calls.toggleCamera()"
        >
          <Video v-if="calls.camOn" class="h-5 w-5" aria-hidden="true" />
          <VideoOff v-else class="h-5 w-5" aria-hidden="true" />
        </button>
        <button
          v-if="calls.camOn && calls.cameras.length > 1"
          type="button"
          :class="CONTROL"
          :aria-label="t('calls.switchCamera')"
          @click="calls.switchCamera()"
        >
          <SwitchCamera class="h-5 w-5" aria-hidden="true" />
        </button>
        <button
          v-if="calls.canScreenShare"
          type="button"
          :class="[CONTROL, calls.screenOn ? 'bg-white text-gray-900 hover:bg-gray-200' : '']"
          :aria-label="calls.screenOn ? t('calls.stopShare') : t('calls.shareScreen')"
          :aria-pressed="calls.screenOn"
          @click="calls.toggleScreenShare()"
        >
          <MonitorUp class="h-5 w-5" aria-hidden="true" />
        </button>
        <label v-if="calls.canPickOutput" class="flex items-center gap-1 rounded-full bg-white/10 px-3 py-2 text-sm">
          <Volume2 class="h-4 w-4 shrink-0" aria-hidden="true" />
          <span class="sr-only">{{ t("calls.speaker") }}</span>
          <select
            class="max-w-[10rem] truncate bg-transparent text-white focus:outline-none [&>option]:text-gray-900"
            :value="calls.outputId"
            @change="calls.setOutput(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="device in calls.outputs" :key="device.deviceId" :value="device.deviceId">
              {{ device.label || t("calls.defaultSpeaker") }}
            </option>
          </select>
        </label>
        <button
          type="button"
          class="flex h-14 w-14 items-center justify-center rounded-full bg-red-600 text-white hover:bg-red-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-400"
          :aria-label="t('calls.hangUp')"
          data-testid="call-hangup"
          @click="calls.hangup()"
        >
          <PhoneOff class="h-6 w-6" aria-hidden="true" />
        </button>
      </footer>
    </section>

    <!-- Minimised: a pill that stays out of the way -->
    <div
      v-else-if="showPill"
      class="fixed bottom-20 end-4 z-[70] flex items-center gap-2 rounded-full bg-gray-950 py-1.5 pe-1.5 ps-4 text-white shadow-pop lg:bottom-6"
      data-testid="call-pill"
      role="region"
      :aria-label="t('calls.dialogLabel', { kind: kindLabel })"
    >
      <span class="max-w-[9rem] truncate text-sm" dir="auto">{{ title || kindLabel }}</span>
      <span class="text-xs tabular-nums text-gray-300" role="status">{{ status }}</span>
      <button type="button" :class="CONTROL" class="h-9 w-9" :aria-label="t('calls.restore')" @click="calls.minimised = false">
        <Maximize2 class="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        class="flex h-9 w-9 items-center justify-center rounded-full bg-red-600 hover:bg-red-700"
        :aria-label="t('calls.hangUp')"
        @click="calls.hangup()"
      >
        <PhoneOff class="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  </Teleport>
</template>
