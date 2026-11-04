<script setup lang="ts">
import { useI18n } from "vue-i18n";

import AdminLayout from "@/components/admin/AdminLayout.vue";
import CapabilityMatrix from "@/components/admin/CapabilityMatrix.vue";

const { t } = useI18n();
</script>

<template>
  <AdminLayout :title="t('admin.sections.capabilities')">
    <CapabilityMatrix />
  </AdminLayout>
</template>
