<script setup lang="ts">
import { UserCheck, UserPlus } from "lucide-vue-next";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { graphService } from "@/services/graph";
import { useToastStore } from "@/stores/toasts";

const props = defineProps<{ userId: string; following: boolean }>();
const emit = defineEmits<{ change: [on: boolean] }>();

const { t } = useI18n();
const toasts = useToastStore();
const isFollowing = ref(props.following);
// Follow state may resolve asynchronously on the profile; keep in sync.
watch(
  () => props.following,
  (v) => (isFollowing.value = v),
);
const busy = ref(false);

async function toggle() {
  if (busy.value) return;
  busy.value = true;
  const next = !isFollowing.value;
  isFollowing.value = next;
  try {
    if (next) await graphService.follow(props.userId);
    else await graphService.unfollow(props.userId);
    emit("change", next);
  } catch (e) {
    isFollowing.value = !next;
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <button :class="isFollowing ? 'btn-ghost' : 'btn-primary'" :disabled="busy" @click="toggle">
    <component :is="isFollowing ? UserCheck : UserPlus" class="h-4 w-4" />
    {{ isFollowing ? t("profile.following") : t("profile.follow") }}
  </button>
</template>
