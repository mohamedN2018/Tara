<script setup lang="ts">
import { Check, Plus } from "lucide-vue-next";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { pageService } from "@/services/pages";
import { useToastStore } from "@/stores/toasts";

// Follow / Following for a page (graph). Optimistic, rolled back on failure.
const props = withDefaults(defineProps<{ pageId: string; name: string; following: boolean; compact?: boolean }>(), {
  compact: false,
});
const emit = defineEmits<{ changed: [following: boolean] }>();

const { t } = useI18n();
const toasts = useToastStore();
const on = ref(props.following);
const busy = ref(false);
watch(
  () => props.following,
  (v) => (on.value = v),
);

async function toggle() {
  if (busy.value) return;
  busy.value = true;
  const next = !on.value;
  on.value = next;
  try {
    if (next) await pageService.follow(props.pageId);
    else await pageService.unfollow(props.pageId);
    emit("changed", next);
    toasts.success(t(next ? "pageHub.header.followed" : "pageHub.header.unfollowed", { name: props.name }));
  } catch (e) {
    on.value = !next;
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <button
    type="button"
    :class="[on ? 'btn-soft' : 'btn-primary', compact ? 'px-3 py-1.5' : '']"
    :disabled="busy"
    :aria-pressed="on"
    data-testid="page-follow"
    @click="toggle"
  >
    <component :is="on ? Check : Plus" class="h-4 w-4" aria-hidden="true" />
    {{ on ? t("pageHub.header.following") : t("pageHub.header.follow") }}
  </button>
</template>
