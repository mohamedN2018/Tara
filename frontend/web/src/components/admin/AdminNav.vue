<script setup lang="ts">
import { Activity, ClipboardList, KeyRound, ShieldCheck } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();
const auth = useAuthStore();

// Each section shows only for someone holding the capability its page needs.
const sections = computed(() =>
  [
    { to: "/admin", label: "admin.sections.overview", icon: ShieldCheck, cap: null },
    { to: "/admin/capabilities", label: "admin.sections.capabilities", icon: KeyRound, cap: "admin.capabilities.manage" },
    { to: "/admin/audit", label: "admin.sections.audit", icon: ClipboardList, cap: "admin.audit.view" },
    { to: "/admin/monitor", label: "admin.sections.monitor", icon: Activity, cap: "admin.monitor.view" },
  ].filter((s) => s.cap === null || auth.can(s.cap)),
);
</script>

<template>
  <nav v-if="sections.length > 1" class="mb-4 flex flex-wrap gap-2" :aria-label="t('admin.sections.label')" data-testid="admin-nav">
    <RouterLink
      v-for="s in sections"
      :key="s.to"
      :to="s.to"
      class="btn-ghost inline-flex items-center gap-1.5 text-sm"
      exact-active-class="bg-brand-50 font-semibold text-brand-700 dark:bg-brand-950/40 dark:text-brand-300"
    >
      <component :is="s.icon" class="h-4 w-4" aria-hidden="true" />
      {{ t(s.label) }}
    </RouterLink>
  </nav>
</template>
