<script setup lang="ts">
import { Cake, MessageCircle } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { birthdayDate, birthdaysService, birthdayWeekday, type FriendBirthday, splitBirthdays } from "@/services/birthdays";
import { chatService } from "@/services/chat";
import { useChatDockStore } from "@/stores/chatDock";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

// Friends > Birthdays: today's birthdays, then the rest of this week. Identity
// decides who shows (friends who share their birthday with friends, day and
// month only, nobody across a block); this only lays them out.
const { t, locale } = useI18n();
const router = useRouter();
const directory = useDirectoryStore();
const chatDock = useChatDockStore();
const toasts = useToastStore();

const rows = ref<FriendBirthday[] | null>(null);
const failed = ref(false);
const opening = ref("");

const groups = computed(() => {
  const { today, upcoming } = splitBirthdays(rows.value ?? []);
  return [
    { id: "today", title: t("socialShell.birthdays.today"), rows: today },
    { id: "upcoming", title: t("socialShell.birthdays.upcoming"), rows: upcoming },
  ].filter((g) => g.rows.length);
});

function when(b: FriendBirthday): string {
  if (b.days_until === 0) return t("socialShell.birthdays.todayBadge");
  if (b.days_until === 1) return `${t("socialShell.birthdays.tomorrow")} · ${birthdayDate(b, locale.value)}`;
  return `${birthdayWeekday(b.days_until, locale.value)} · ${birthdayDate(b, locale.value)}`;
}

async function load() {
  failed.value = false;
  rows.value = null;
  try {
    rows.value = await birthdaysService.list(7);
  } catch {
    failed.value = true;
  }
}

async function message(id: string) {
  if (opening.value) return;
  opening.value = id;
  try {
    const convo = await chatService.openDm(id);
    if (chatDock.available()) chatDock.open(convo.id);
    else router.push(`/messages/${convo.id}`);
  } catch (e) {
    toasts.error(e);
  } finally {
    opening.value = "";
  }
}

onMounted(load);
</script>

<template>
  <div class="space-y-4" data-testid="friends-birthdays">
    <ErrorState v-if="failed" @retry="load" />
    <LoadingSkeleton v-else-if="rows === null" :rows="3" />
    <EmptyState v-else-if="!groups.length" class="card">{{ t("socialShell.birthdays.none") }}</EmptyState>
    <section
      v-for="g in groups"
      :key="g.id"
      class="card p-3"
      :aria-labelledby="`birthdays-${g.id}`"
      :data-testid="`birthdays-${g.id}`"
    >
      <h3 :id="`birthdays-${g.id}`" class="mb-2 flex items-center gap-2 px-1 text-lg font-bold">
        <Cake class="h-5 w-5 text-accent-700 dark:text-accent-300" aria-hidden="true" /> {{ g.title }}
      </h3>
      <ul class="divide-y divide-gray-100 dark:divide-gray-800">
        <li v-for="b in g.rows" :key="b.account_id" class="flex items-center gap-3 py-2" data-testid="birthday-row" :data-account-id="b.account_id">
          <RouterLink :to="{ name: 'profile-by-id', params: { id: b.account_id } }" class="shrink-0" tabindex="-1" aria-hidden="true">
            <UserAvatar :name="directory.label(b.account_id)" :media-id="directory.avatarOf(b.account_id)" :size="52" />
          </RouterLink>
          <div class="min-w-0 flex-1 text-start">
            <RouterLink :to="{ name: 'profile-by-id', params: { id: b.account_id } }" class="block truncate font-semibold hover:underline">
              <bdi>{{ directory.label(b.account_id) }}</bdi>
            </RouterLink>
            <p class="truncate text-sm text-gray-600 dark:text-gray-400">{{ when(b) }}</p>
          </div>
          <button
            type="button"
            class="btn-soft shrink-0 px-3 py-1.5"
            :disabled="opening === b.account_id"
            :aria-label="t('socialShell.birthdays.messageName', { name: directory.label(b.account_id) })"
            data-testid="birthday-message"
            @click="message(b.account_id)"
          >
            <MessageCircle class="h-4 w-4" aria-hidden="true" />
            <span class="hidden sm:inline">{{ t("socialShell.birthdays.message") }}</span>
          </button>
        </li>
      </ul>
    </section>
    <p v-if="rows !== null && !failed" class="px-1 text-xs text-gray-600 dark:text-gray-400">{{ t("socialShell.birthdays.privacyNote") }}</p>
  </div>
</template>
