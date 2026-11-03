<script setup lang="ts">
// Voice and video call buttons for a conversation header. Hidden while calls
// are off on the server, and for conversation types that cannot be called.
import { Phone, Video } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useCallStore } from "@/stores/calls";

const props = defineProps<{ conversationId: string; conversationType?: string | null }>();
const { t } = useI18n();
const calls = useCallStore();

const CALLABLE = new Set(["dm", "group", "marketplace"]);
const visible = computed(() => calls.enabled && CALLABLE.has(props.conversationType ?? ""));
</script>

<template>
  <template v-if="visible">
    <button
      type="button"
      class="btn-ghost px-2"
      :aria-label="t('calls.startVoice')"
      :title="t('calls.startVoice')"
      :disabled="calls.busy"
      data-testid="call-start-audio"
      @click="calls.start(conversationId, 'audio')"
    >
      <Phone class="h-5 w-5" aria-hidden="true" />
    </button>
    <button
      type="button"
      class="btn-ghost px-2"
      :aria-label="t('calls.startVideo')"
      :title="t('calls.startVideo')"
      :disabled="calls.busy"
      data-testid="call-start-video"
      @click="calls.start(conversationId, 'video')"
    >
      <Video class="h-5 w-5" aria-hidden="true" />
    </button>
  </template>
</template>
