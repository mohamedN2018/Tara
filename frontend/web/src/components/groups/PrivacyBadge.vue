<script setup lang="ts">
import { EyeOff, Globe2, Lock } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

import type { GroupPrivacy } from "@/services/groups";

defineProps<{ privacy: GroupPrivacy }>();
const { t } = useI18n();
const ICONS = { public: Globe2, private: Lock, hidden: EyeOff } as const;
</script>

<template>
  <span class="inline-flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400" data-testid="group-privacy">
    <component :is="ICONS[privacy]" class="h-3.5 w-3.5" aria-hidden="true" />
    {{ t(`groups.privacy.${privacy}`) }}
  </span>
</template>
