<script setup lang="ts">
import { UserCheck, UserPlus } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import { graphService } from "@/services/graph";

const props = defineProps<{ userId: string; following: boolean }>();

const { t } = useI18n();
const isFollowing = ref(props.following);
const busy = ref(false);

async function toggle() {
  if (busy.value) return;
  busy.value = true;
  const next = !isFollowing.value;
  isFollowing.value = next;
  try {
    if (next) await graphService.follow(props.userId);
    else await graphService.unfollow(props.userId);
  } catch {
    isFollowing.value = !next;
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
