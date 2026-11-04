<script setup lang="ts">
import { Activity, BadgeCheck, ClipboardList, Flag, KeyRound, LifeBuoy, Megaphone, ShieldAlert, ShieldCheck, UserCog, Users } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { badgeText } from "@/lib/chat";
import { chatService } from "@/services/chat";
import { useAuthStore } from "@/stores/auth";

/**
 * The console's section list: a vertical rail beside the content on desktop,
 * a row of scrollable chips on phones. Each section shows only to someone who
 * holds a capability its page needs (the router and the server check the same keys).
 */
withDefaults(defineProps<{ vertical?: boolean }>(), { vertical: false });

const { t } = useI18n();
const auth = useAuthStore();

interface AdminSection {
  to: string;
  label: string;
  icon: unknown;
  caps: string[] | null;
  exact?: boolean;
}

const ALL: AdminSection[] = [
  { to: "/admin", label: "admin.sections.overview", icon: ShieldCheck, caps: null, exact: true },
  { to: "/admin/moderation", label: "safety.console.sections.moderation", icon: ShieldAlert, caps: ["moderation.case.view", "moderation.appeal.view"] },
  { to: "/admin/support", label: "chatTeam.supportInbox", icon: LifeBuoy, caps: ["moderation.case.view"] },
  { to: "/ads/review", label: "safety.console.sections.adReview", icon: BadgeCheck, caps: ["ads.review"] },
  { to: "/admin/users", label: "admin.sections.users", icon: Users, caps: ["admin.users.view"] },
  { to: "/admin/notices", label: "safety.console.sections.notices", icon: Megaphone, caps: ["admin.notices.send"] },
  { to: "/admin/roles", label: "safety.console.sections.roles", icon: UserCog, caps: ["admin.roles.manage"] },
  { to: "/admin/capabilities", label: "admin.sections.capabilities", icon: KeyRound, caps: ["admin.capabilities.manage"] },
  { to: "/admin/flags", label: "safety.console.sections.flags", icon: Flag, caps: ["admin.flags.manage"] },
  { to: "/admin/audit", label: "admin.sections.audit", icon: ClipboardList, caps: ["admin.audit.view"] },
  { to: "/admin/monitor", label: "admin.sections.monitor", icon: Activity, caps: ["admin.monitor.view"] },
];

const sections = computed(() => ALL.filter((s) => s.caps === null || auth.canAny(s.caps)));

// The support inbox's badge: members' threads nobody on the team has read yet.
const supportUnread = ref(0);
onMounted(async () => {
  if (!auth.canAny(["moderation.case.view"])) return;
  try {
    supportUnread.value = await chatService.teamUnread();
  } catch {
    // No badge rather than a wrong one.
  }
});
const badgeFor = (s: AdminSection) => (s.to === "/admin/support" ? supportUnread.value : 0);
</script>

<template>
  <nav :aria-label="t('admin.sections.label')" data-testid="admin-nav">
    <ul v-if="vertical" class="space-y-0.5">
      <li v-for="s in sections" :key="s.to">
        <RouterLink
          :to="s.to"
          class="nav-item"
          :active-class="s.exact ? '' : 'nav-item-active'"
          :exact-active-class="'nav-item-active'"
          :data-testid="`admin-nav-${s.to.split('/').pop()}`"
        >
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-300">
            <component :is="s.icon" class="h-5 w-5" aria-hidden="true" />
          </span>
          <span class="truncate">{{ t(s.label) }}</span>
          <span
            v-if="badgeFor(s)"
            class="badge ms-auto shrink-0"
            :aria-label="t('chatTeam.unreadThreads', { count: badgeFor(s) }, badgeFor(s))"
            data-testid="admin-support-unread"
          >{{ badgeText(badgeFor(s)) }}</span>
        </RouterLink>
      </li>
    </ul>
    <ul v-else class="-mx-2 flex gap-2 overflow-x-auto px-2 pb-1">
      <li v-for="s in sections" :key="s.to" class="shrink-0">
        <RouterLink
          :to="s.to"
          class="chip inline-flex items-center gap-1.5 whitespace-nowrap"
          :active-class="s.exact ? '' : 'chip-active'"
          exact-active-class="chip-active"
        >
          <component :is="s.icon" class="h-4 w-4" aria-hidden="true" />
          {{ t(s.label) }}
          <span v-if="badgeFor(s)" class="badge" :aria-label="t('chatTeam.unreadThreads', { count: badgeFor(s) }, badgeFor(s))">{{ badgeText(badgeFor(s)) }}</span>
        </RouterLink>
      </li>
    </ul>
  </nav>
</template>
