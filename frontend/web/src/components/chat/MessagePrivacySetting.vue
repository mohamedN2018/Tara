<script setup lang="ts">
// "Who can message you": everyone (strangers wait in message requests),
// friends of friends (people with a mutual friend wait in requests, nobody
// else can start a chat) or friends only. The chat service enforces it on
// every new chat; this only reads and sets it. Existing chats stay open.
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { chatService, MESSAGE_FROM, type MessageFrom } from "@/services/chat";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const toasts = useToastStore();

const value = ref<MessageFrom | null>(null);
const unavailable = ref(false);
const saving = ref(false);

onMounted(async () => {
  try {
    value.value = await chatService.messageSettings();
  } catch {
    unavailable.value = true;
  }
});

async function choose(next: MessageFrom) {
  if (saving.value || next === value.value) return;
  const before = value.value;
  value.value = next;
  saving.value = true;
  try {
    value.value = await chatService.setMessageSettings(next);
    toasts.success(t("chatTeam.privacy.saved"));
  } catch (err) {
    value.value = before;
    toasts.error(err);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section id="messaging" class="card mb-4 scroll-mt-20 p-4" data-testid="message-privacy">
    <h2 class="mb-1 font-semibold">{{ t("chatTeam.privacy.title") }}</h2>
    <p v-if="unavailable" class="text-sm text-gray-500 dark:text-gray-400">{{ t("chatTeam.privacy.unavailable") }}</p>
    <fieldset v-else :disabled="value === null || saving">
      <legend class="mb-2 text-sm text-gray-700 dark:text-gray-300">{{ t("chatTeam.privacy.hint") }}</legend>
      <div class="space-y-1">
        <label
          v-for="p in MESSAGE_FROM"
          :key="p"
          class="flex cursor-pointer items-start gap-3 rounded-xl p-2 hover:bg-gray-50 focus-within:ring-2 focus-within:ring-brand-400 dark:hover:bg-gray-800/60"
          :data-testid="`message-from-${p}`"
        >
          <input type="radio" name="message-from" class="mt-1 h-4 w-4 accent-brand-600" :value="p" :checked="value === p" @change="choose(p)" />
          <span class="min-w-0">
            <span class="block text-sm font-medium">{{ t(`chatTeam.privacy.${p}`) }}</span>
            <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t(`chatTeam.privacy.${p}Hint`) }}</span>
          </span>
        </label>
      </div>
    </fieldset>
  </section>
</template>
