<script setup lang="ts">
// "A call is in progress — Join": shown above a conversation while it has a
// live call this tab is not part of (a reload, another device, a late joiner).
import { Phone, Video } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useAuthStore } from "@/stores/auth";
import { useCallStore } from "@/stores/calls";

const props = defineProps<{ conversationId: string }>();
const { t } = useI18n();
const calls = useCallStore();
const auth = useAuthStore();

const live = computed(() => (calls.enabled ? calls.active[props.conversationId] ?? null : null));
const show = computed(() => {
  const call = live.value;
  if (!call || calls.call?.id === call.id || calls.incoming?.call_id === call.id) return false;
  // A call still ringing for me is answered from the incoming sheet instead.
  const mine = call.participants.find((p) => p.account_id === auth.account?.id);
  return !(call.state === "ringing" && mine?.state === "ringing" && calls.phase === "incoming");
});
const joined = computed(() => (live.value?.participants ?? []).filter((p) => p.in_room).length);
</script>

<template>
  <div
    v-if="show && live"
    class="flex items-center gap-2 border-b border-brand-200 bg-brand-50 px-3 py-2 text-sm text-brand-800 dark:border-brand-900 dark:bg-brand-950/60 dark:text-brand-100"
    role="status"
    data-testid="call-banner"
  >
    <Video v-if="live.kind === 'video'" class="h-4 w-4 shrink-0" aria-hidden="true" />
    <Phone v-else class="h-4 w-4 shrink-0" aria-hidden="true" />
    <span class="min-w-0 flex-1 truncate">
      {{ live.kind === "video" ? t("calls.bannerVideo") : t("calls.bannerVoice") }}
      <template v-if="joined"> · {{ t("calls.inCallCount", { count: joined }, joined) }}</template>
    </span>
    <button
      type="button"
      class="btn-primary shrink-0 px-3 py-1 text-xs"
      :disabled="calls.busy"
      data-testid="call-rejoin"
      @click="calls.rejoin(live.id)"
    >
      {{ t("calls.join") }}
    </button>
  </div>
</template>
