<script setup lang="ts">
import { useI18n } from "vue-i18n";

import AdminLayout from "@/components/admin/AdminLayout.vue";
import FeatureFlagsPanel from "@/components/admin/FeatureFlagsPanel.vue";

const { t } = useI18n();
</script>

<template>
  <AdminLayout :title="t('safety.console.sections.flags')" :subtitle="t('safety.console.flags.subtitle')">
    <FeatureFlagsPanel />
  </AdminLayout>
</template>
