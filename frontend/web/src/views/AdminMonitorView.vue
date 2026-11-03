<script setup lang="ts">
import { useI18n } from "vue-i18n";

import AdminNav from "@/components/admin/AdminNav.vue";
import MonitorDashboard from "@/components/admin/MonitorDashboard.vue";
import AppShell from "@/components/layout/AppShell.vue";

const { t } = useI18n();
</script>

<template>
  <AppShell>
    <h1 class="mb-4 text-xl font-bold">{{ t("nav.admin") }}</h1>
    <AdminNav />
    <MonitorDashboard />
  </AppShell>
</template>
