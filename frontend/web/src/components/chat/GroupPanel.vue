<script setup lang="ts">
import { Crown, UserMinus, X } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { chatService } from "@/services/chat";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";
import type { Conversation } from "@/types";

const props = defineProps<{ conversation: Conversation; selfId: string }>();
const emit = defineEmits<{ close: []; changed: []; left: []; add: [] }>();

const { t } = useI18n();
const directory = useDirectoryStore();
const toasts = useToastStore();
const open = ref(true);
useEscapeKey(open, () => emit("close"));
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);

const title = ref(props.conversation.title);
const busy = ref(false);
const isAdmin = computed(
  () => props.conversation.member_states.find((s) => s.account_id === props.selfId)?.role === "admin",
);

async function run(action: () => Promise<unknown>, after: "changed" | "left" = "changed") {
  if (busy.value) return;
  busy.value = true;
  try {
    await action();
    if (after === "left") emit("left");
    else emit("changed");
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

const rename = () =>
  title.value.trim() && run(() => chatService.renameGroup(props.conversation.id, title.value.trim()));
const remove = (id: string) => run(() => chatService.removeMember(props.conversation.id, id));
const leave = () => run(() => chatService.removeMember(props.conversation.id, props.selfId), "left");
const setRole = (id: string, role: string) =>
  run(() => chatService.setMemberRole(props.conversation.id, id, role));
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 backdrop-blur-sm p-0 sm:items-center sm:p-4">
    <div class="fixed inset-0" @click="emit('close')" />
    <div
      ref="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="group-panel-title"
      tabindex="-1"
      class="card relative z-10 animate-pop-in shadow-pop max-h-[92vh] w-full overflow-y-auto rounded-b-none rounded-t-2xl p-4 sm:max-w-md sm:rounded-2xl sm:p-5"
    >
      <div class="mb-4 flex items-center justify-between">
        <h2 id="group-panel-title" class="text-lg font-bold">{{ t("messages.groupInfo") }}</h2>
        <button class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('market.close')" @click="emit('close')">
          <X class="h-5 w-5" />
        </button>
      </div>

      <form v-if="isAdmin" class="mb-4 flex gap-2" @submit.prevent="rename">
        <input v-model="title" class="input" dir="auto" maxlength="160" :aria-label="t('messages.groupName')" />
        <button class="btn-ghost shrink-0" :disabled="busy || !title.trim()">{{ t("settings.save") }}</button>
      </form>

      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-sm font-semibold">{{ t("messages.membersCount", conversation.members.length) }}</h3>
        <button v-if="isAdmin" class="btn-ghost text-sm" @click="emit('add')">{{ t("messages.addMembers") }}</button>
      </div>
      <ul class="space-y-1" data-testid="group-members">
        <li v-for="m in conversation.member_states" :key="m.account_id" class="flex items-center gap-3 rounded-lg px-2 py-1.5">
          <UserAvatar :name="directory.label(m.account_id)" :media-id="directory.avatarOf(m.account_id)" :size="32" />
          <RouterLink :to="{ name: 'profile-by-id', params: { id: m.account_id } }" class="min-w-0 flex-1 truncate text-sm hover:underline" dir="auto">
            {{ m.account_id === selfId ? t("messages.you") : directory.label(m.account_id) }}
          </RouterLink>
          <span v-if="m.role === 'admin'" class="inline-flex items-center gap-1 text-xs text-amber-600">
            <Crown class="h-3.5 w-3.5" /> {{ t("messages.admin") }}
          </span>
          <template v-if="isAdmin && m.account_id !== selfId">
            <button
              class="btn-ghost px-2 text-xs"
              :disabled="busy"
              @click="setRole(m.account_id, m.role === 'admin' ? 'member' : 'admin')"
            >
              {{ m.role === "admin" ? t("messages.removeAdmin") : t("messages.makeAdmin") }}
            </button>
            <button
              class="rounded-full p-1 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40"
              :aria-label="t('messages.removeMember')"
              :title="t('messages.removeMember')"
              :disabled="busy"
              @click="remove(m.account_id)"
            >
              <UserMinus class="h-4 w-4" />
            </button>
          </template>
        </li>
      </ul>

      <button class="btn-ghost mt-4 w-full justify-center text-red-600" :disabled="busy" @click="leave">
        {{ t("messages.leaveGroup") }}
      </button>
    </div>
  </div>
</template>
