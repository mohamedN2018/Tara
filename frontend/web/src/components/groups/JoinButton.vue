<script setup lang="ts">
import { Bell, BellOff, Check, ChevronDown, Clock, LogOut, UserPlus, X } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { useEscapeKey } from "@/lib/useEscapeKey";
import { type Group, GROUP_ERRORS, groupsService, joinState } from "@/services/groups";
import { useToastStore } from "@/stores/toasts";

// Join / Request to join / Requested (cancel) / Invited (accept, decline) /
// Joined (post notifications, leave). The parent reloads the group on `changed`.
const props = defineProps<{ group: Group }>();
const emit = defineEmits<{ changed: [] }>();

const { t } = useI18n();
const toasts = useToastStore();
const busy = ref(false);
const menuOpen = ref(false);
useEscapeKey(menuOpen, () => (menuOpen.value = false));

const state = computed(() => joinState(props.group));
const ref_ = computed(() => props.group.handle || props.group.id);

async function run(action: () => Promise<unknown>, success?: string) {
  if (busy.value) return;
  busy.value = true;
  menuOpen.value = false;
  try {
    await action();
    if (success) toasts.success(success);
    emit("changed");
  } catch (e) {
    toasts.error(e, GROUP_ERRORS);
  } finally {
    busy.value = false;
  }
}

async function join() {
  await run(async () => {
    const m = await groupsService.join(ref_.value);
    toasts.success(t(m.state === "active" ? "groups.join.joined" : "groups.join.requestSent"));
  });
}
const cancel = () => run(() => groupsService.cancelJoin(ref_.value), t("groups.join.cancelled"));
const decline = () => run(() => groupsService.cancelJoin(ref_.value), t("groups.join.declined"));
async function leave() {
  if (!window.confirm(t("groups.join.leaveConfirm", { name: props.group.name }))) return;
  await run(() => groupsService.leave(ref_.value), t("groups.join.left"));
}
const toggleNotify = () =>
  run(
    () => groupsService.setNotifyPosts(ref_.value, !props.group.viewer.notify_posts),
    t(props.group.viewer.notify_posts ? "groups.join.notifyOff" : "groups.join.notifyOn"),
  );
</script>

<template>
  <div class="flex flex-wrap items-center gap-2" data-testid="group-join">
    <button v-if="state === 'join'" type="button" class="btn-gradient" :disabled="busy" @click="join">
      <UserPlus class="h-4 w-4" aria-hidden="true" /> {{ t("groups.join.join") }}
    </button>
    <button v-else-if="state === 'request'" type="button" class="btn-gradient" :disabled="busy" @click="join">
      <UserPlus class="h-4 w-4" aria-hidden="true" /> {{ t("groups.join.request") }}
    </button>
    <button v-else-if="state === 'requested'" type="button" class="btn-outline" :disabled="busy" @click="cancel">
      <Clock class="h-4 w-4" aria-hidden="true" /> {{ t("groups.join.requested") }}
      <span class="sr-only">{{ t("groups.join.cancelHint") }}</span>
    </button>
    <template v-else-if="state === 'invited'">
      <button type="button" class="btn-gradient" :disabled="busy" @click="join">
        <Check class="h-4 w-4" aria-hidden="true" /> {{ t("groups.join.accept") }}
      </button>
      <button type="button" class="btn-outline" :disabled="busy" @click="decline">
        <X class="h-4 w-4" aria-hidden="true" /> {{ t("groups.join.decline") }}
      </button>
    </template>
    <div v-else class="relative">
      <button
        type="button"
        class="btn-soft"
        :disabled="busy"
        aria-haspopup="menu"
        :aria-expanded="menuOpen"
        @click="menuOpen = !menuOpen"
      >
        <Check class="h-4 w-4" aria-hidden="true" /> {{ t("groups.join.joinedLabel") }}
        <ChevronDown class="h-4 w-4" aria-hidden="true" />
      </button>
      <template v-if="menuOpen">
        <div class="fixed inset-0 z-40" @click="menuOpen = false" />
        <div class="popover absolute start-0 z-50 mt-1 w-60 p-1" role="menu">
          <button
            type="button"
            role="menuitemcheckbox"
            :aria-checked="group.viewer.notify_posts"
            class="nav-item w-full"
            @click="toggleNotify"
          >
            <Bell v-if="!group.viewer.notify_posts" class="h-4 w-4" aria-hidden="true" />
            <BellOff v-else class="h-4 w-4" aria-hidden="true" />
            {{ group.viewer.notify_posts ? t("groups.join.notifyDisable") : t("groups.join.notifyEnable") }}
          </button>
          <button type="button" role="menuitem" class="nav-item w-full text-red-600 dark:text-red-400" @click="leave">
            <LogOut class="h-4 w-4 rtl:rotate-180" aria-hidden="true" /> {{ t("groups.join.leave") }}
          </button>
        </div>
      </template>
    </div>
  </div>
</template>
