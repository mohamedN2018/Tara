<script setup lang="ts">
// The Page header's messaging action. A visitor gets "Message": it opens (or
// reuses) their conversation with the Page, which the page's team answers as
// the Page. The team (owner, admins, editors, moderators) gets "Page inbox"
// instead. Nothing shows for a page that is not published or for other team
// roles; the server checks all of it again (404 / 400).
import { Inbox, MessageCircle } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { badgeText } from "@/lib/chat";
import { chatService } from "@/services/chat";
import type { Page } from "@/services/pages";
import { useToastStore } from "@/stores/toasts";

const props = defineProps<{ page: Pick<Page, "id" | "status" | "my_role"> }>();
const { t } = useI18n();
const router = useRouter();
const toasts = useToastStore();
const busy = ref(false);

const TEAM_ROLES = ["owner", "admin", "editor", "moderator"];
const answers = computed(() => TEAM_ROLES.includes(props.page.my_role ?? ""));
const canWrite = computed(() => !props.page.my_role && props.page.status === "published");

// The team's badge: conversations nobody on the team has read yet.
const unread = ref(0);
async function loadUnread() {
  unread.value = 0;
  if (!answers.value) return;
  try {
    unread.value = await chatService.teamUnread(props.page.id);
  } catch {
    // No badge rather than a wrong one.
  }
}
onMounted(loadUnread);
watch(() => [props.page.id, answers.value], loadUnread);

async function write() {
  if (busy.value) return;
  busy.value = true;
  try {
    const conversation = await chatService.openPage(props.page.id);
    await router.push({ name: "messages", params: { id: conversation.id } });
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <RouterLink v-if="answers" :to="`/pages/id/${page.id}/inbox`" class="btn-soft" data-testid="page-inbox-link">
    <Inbox class="h-4 w-4" aria-hidden="true" /> {{ t("chatTeam.pageInbox") }}
    <span v-if="unread" class="badge" :aria-label="t('chatTeam.unreadThreads', { count: unread }, unread)" data-testid="page-inbox-unread">{{ badgeText(unread) }}</span>
  </RouterLink>
  <button v-else-if="canWrite" type="button" class="btn-soft" :disabled="busy" data-testid="page-message" @click="write">
    <MessageCircle class="h-4 w-4" aria-hidden="true" /> {{ busy ? t("chatTeam.opening") : t("chatTeam.message") }}
  </button>
</template>
