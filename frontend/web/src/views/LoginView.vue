<script setup lang="ts">
// `/login` stays for old links and for the route guard's `?redirect=`. The same
// card sits on `/` for visitors (decision 5.7).
import { useI18n } from "vue-i18n";

import LoginCard from "@/components/auth/LoginCard.vue";
import AuthLayout from "@/components/brand/AuthLayout.vue";

const { t } = useI18n();
</script>

<template>
  <AuthLayout :title="t('auth.welcome')">
    <LoginCard />
  </AuthLayout>
</template>
