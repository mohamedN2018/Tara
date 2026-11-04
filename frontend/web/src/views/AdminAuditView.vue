<script setup lang="ts">
import { useI18n } from "vue-i18n";

import AdminLayout from "@/components/admin/AdminLayout.vue";
import AuditLog from "@/components/admin/AuditLog.vue";

const { t } = useI18n();
</script>

<template>
  <AdminLayout :title="t('admin.sections.audit')">
    <AuditLog />
  </AdminLayout>
</template>
