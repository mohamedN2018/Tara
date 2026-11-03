<script setup lang="ts">
import { Flag, MoreHorizontal, Settings2, UserPlus, UsersRound } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { useEscapeKey } from "@/lib/useEscapeKey";
import { useMediaUrl } from "@/lib/useMediaUrl";
import { type Group, groupPath, manageSections } from "@/services/groups";

import JoinButton from "./JoinButton.vue";
import PrivacyBadge from "./PrivacyBadge.vue";

// The group's header: wide cover, name, privacy, size, the join button,
// invite, report and the dashboard link for staff.
const props = defineProps<{ group: Group }>();
const emit = defineEmits<{ changed: []; invite: []; report: [] }>();

const { t } = useI18n();
const cover = useMediaUrl(() => props.group.cover_media_id);
const menuOpen = ref(false);
useEscapeKey(menuOpen, () => (menuOpen.value = false));
const canManage = computed(() => manageSections(props.group.viewer?.can).length > 0);
const isMember = computed(() => props.group.viewer?.state === "active");
</script>

<template>
  <header class="card overflow-hidden" aria-labelledby="group-title">
    <div class="relative h-40 bg-tara-gradient sm:h-60">
      <img v-if="cover" :src="cover" alt="" class="h-full w-full object-cover" />
      <span v-else class="flex h-full w-full items-center justify-center text-white/80">
        <UsersRound class="h-14 w-14" aria-hidden="true" />
      </span>
    </div>
    <div class="space-y-3 p-4 sm:p-6">
      <div class="flex flex-wrap items-start gap-3">
        <div class="min-w-0 flex-1 space-y-1">
          <h1 id="group-title" class="text-2xl font-extrabold leading-tight" dir="auto">{{ group.name }}</h1>
          <p class="flex flex-wrap items-center gap-x-2 text-sm text-gray-500 dark:text-gray-400">
            <PrivacyBadge :privacy="group.privacy" />
            <span aria-hidden="true">·</span>
            <span data-testid="group-member-count">{{ t("groups.memberCount", { count: group.member_count }, group.member_count) }}</span>
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <JoinButton :group="group" @changed="emit('changed')" />
          <button v-if="isMember && group.viewer.can.invite" type="button" class="btn-soft" @click="emit('invite')">
            <UserPlus class="h-4 w-4" aria-hidden="true" /> {{ t("groups.invite.button") }}
          </button>
          <RouterLink v-if="canManage" :to="`${groupPath(group)}/manage`" class="btn-outline">
            <Settings2 class="h-4 w-4" aria-hidden="true" /> {{ t("groups.manage.link") }}
          </RouterLink>
          <div class="relative">
            <button
              type="button"
              class="icon-btn"
              :aria-label="t('groups.more')"
              aria-haspopup="menu"
              :aria-expanded="menuOpen"
              @click="menuOpen = !menuOpen"
            >
              <MoreHorizontal class="h-5 w-5" aria-hidden="true" />
            </button>
            <template v-if="menuOpen">
              <div class="fixed inset-0 z-40" @click="menuOpen = false" />
              <div class="popover absolute end-0 z-50 mt-1 w-52 p-1" role="menu">
                <button type="button" role="menuitem" class="nav-item w-full" @click="menuOpen = false; emit('report')">
                  <Flag class="h-4 w-4" aria-hidden="true" /> {{ t("groups.report.title") }}
                </button>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>
  </header>
</template>
