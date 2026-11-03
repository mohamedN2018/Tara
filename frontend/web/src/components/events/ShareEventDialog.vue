<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { postService } from "@/services/post";
import type { TaraEvent } from "@/services/events";
import { useToastStore } from "@/stores/toasts";

import EventDialog from "./EventDialog.vue";

// Share as a post: the post links to the event page. The event's own rules still
// decide who can open it, so a post about a friends-only event shows a 404 page
// to anyone else; the dialog says so.
const props = defineProps<{ event: TaraEvent }>();
const emit = defineEmits<{ close: [] }>();

const { t } = useI18n();
const toasts = useToastStore();
const text = ref("");
const audience = ref<"public" | "friends" | "followers" | "only_me">(
  props.event.audience === "public" ? "public" : "friends",
);
const sending = ref(false);
const link = computed(() => `${window.location.origin}/events/${props.event.id}`);
const AUDIENCES = [
  ["public", "feed.audiencePublic"],
  ["friends", "feed.audienceFriends"],
  ["followers", "feed.audienceFollowers"],
  ["only_me", "feed.audienceOnlyMe"],
] as const;

async function share() {
  if (sending.value) return;
  sending.value = true;
  try {
    const body = [text.value.trim(), `${props.event.title}`, link.value].filter(Boolean).join("\n");
    await postService.create({ body, audience: audience.value });
    toasts.success(t("events.shareSent"));
    emit("close");
  } catch (e) {
    toasts.error(e);
  } finally {
    sending.value = false;
  }
}
</script>

<template>
  <EventDialog :title="t('events.shareTitle')" @close="emit('close')">
    <label for="share-event-text" class="sr-only">{{ t("events.shareText") }}</label>
    <textarea id="share-event-text" v-model="text" class="input min-h-24" rows="3" maxlength="2000" dir="auto" :placeholder="t('events.shareText')" />
    <div class="mt-2 rounded-xl border border-gray-200 p-3 text-sm dark:border-gray-800">
      <p class="font-semibold" dir="auto">{{ event.title }}</p>
      <p class="truncate text-xs text-gray-500 dark:text-gray-400" dir="ltr">{{ link }}</p>
    </div>
    <p v-if="event.audience !== 'public'" class="mt-2 text-xs text-amber-700 dark:text-amber-400">{{ t("events.shareLimited") }}</p>
    <label for="share-event-audience" class="label mt-3">{{ t("feed.audience") }}</label>
    <select id="share-event-audience" v-model="audience" class="input">
      <option v-for="[value, label] in AUDIENCES" :key="value" :value="value">{{ t(label) }}</option>
    </select>
    <div class="mt-3 flex justify-end gap-2">
      <button type="button" class="btn-ghost" @click="emit('close')">{{ t("feed.cancel") }}</button>
      <button type="button" class="btn-primary" :disabled="sending" @click="share">{{ t("events.shareButton") }}</button>
    </div>
  </EventDialog>
</template>
