<script setup lang="ts">
import { useI18n } from "vue-i18n";

import AdminLayout from "@/components/admin/AdminLayout.vue";
import RolesPanel from "@/components/admin/RolesPanel.vue";

const { t } = useI18n();
</script>

<template>
  <AdminLayout :title="t('safety.console.sections.roles')" :subtitle="t('admin.rolesHint')">
    <RolesPanel />
  </AdminLayout>
</template>
