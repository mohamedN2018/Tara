<script setup lang="ts">
// /admin/support — members who used "Contact support". The moderation team
// (moderation.case.view, checked again by the chat service) answers as Tara
// Support; the member never sees which teammate wrote.
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import AdminLayout from "@/components/admin/AdminLayout.vue";
import TeamInbox from "@/components/chat/TeamInbox.vue";

const { t } = useI18n();
const route = useRoute();
</script>

<template>
  <AdminLayout :title="t('chatTeam.supportInbox')" :subtitle="t('chatTeam.supportInboxHint')">
    <TeamInbox :team-name="t('chatTeam.support')" :open-id="typeof route.query.conversation === 'string' ? route.query.conversation : ''" />
  </AdminLayout>
</template>
