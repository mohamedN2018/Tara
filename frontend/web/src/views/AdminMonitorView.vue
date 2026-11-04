<script setup lang="ts">
import { useI18n } from "vue-i18n";

import AdminLayout from "@/components/admin/AdminLayout.vue";
import MonitorDashboard from "@/components/admin/MonitorDashboard.vue";

const { t } = useI18n();
</script>

<template>
  <AdminLayout :title="t('admin.sections.monitor')">
    <MonitorDashboard />
  </AdminLayout>
</template>
