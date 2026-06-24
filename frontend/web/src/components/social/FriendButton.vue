<script setup lang="ts">
import { Check, UserMinus, UserPlus, UserX } from "lucide-vue-next";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { type FriendState, graphService } from "@/services/graph";

const props = defineProps<{ userId: string; state: FriendState; requestId?: string }>();

const { t } = useI18n();
const current = ref<FriendState>(props.state);
// Friend state may resolve asynchronously on the profile; keep in sync.
watch(
  () => props.state,
  (v) => (current.value = v),
);
const busy = ref(false);

async function run(fn: () => Promise<void>, next: FriendState) {
  if (busy.value) return;
  busy.value = true;
  const prev = current.value;
  current.value = next;
  try {
    await fn();
  } catch {
    current.value = prev;
  } finally {
    busy.value = false;
  }
}

const send = () => run(() => graphService.sendFriendRequest(props.userId), "pending_out");
const accept = () => run(() => graphService.acceptFriendRequest(props.requestId ?? ""), "friends");
const remove = () => run(() => graphService.removeFriend(props.userId), "none");
const decline = () => run(() => graphService.declineFriendRequest(props.requestId ?? ""), "none");
</script>

<template>
  <button v-if="current === 'none'" class="btn-primary" :disabled="busy" @click="send">
    <UserPlus class="h-4 w-4" /> {{ t("profile.addFriend") }}
  </button>

  <button v-else-if="current === 'pending_out'" class="btn-ghost" :disabled="busy" @click="remove">
    <UserX class="h-4 w-4" /> {{ t("profile.requestSent") }}
  </button>

  <div v-else-if="current === 'pending_in'" class="flex gap-2">
    <button class="btn-primary" :disabled="busy" @click="accept">
      <Check class="h-4 w-4" /> {{ t("profile.accept") }}
    </button>
    <button class="btn-ghost" :disabled="busy" @click="decline">
      <UserX class="h-4 w-4" /> {{ t("friends.delete") }}
    </button>
  </div>

  <button v-else class="btn-ghost" :disabled="busy" @click="remove">
    <UserMinus class="h-4 w-4" /> {{ t("profile.friendsLabel") }}
  </button>
</template>
