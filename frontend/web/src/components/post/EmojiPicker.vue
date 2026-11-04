<script setup lang="ts">
import { Smile } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import { EMOJIS } from "@/lib/emojis";
import { useEscapeKey } from "@/lib/useEscapeKey";

const emit = defineEmits<{ pick: [emoji: string] }>();
const { t } = useI18n();
const open = ref(false);
useEscapeKey(open, () => (open.value = false));

function pick(emoji: string) {
  emit("pick", emoji);
  open.value = false;
}
</script>

<template>
  <div class="relative shrink-0">
    <button
      type="button"
      class="rounded-full p-2 text-gray-500 transition hover:bg-gray-100 hover:text-brand-600 dark:text-gray-400 dark:hover:bg-gray-800"
      :aria-label="t('homeFeed.emoji.open')"
      :title="t('homeFeed.emoji.open')"
      :aria-expanded="open"
      aria-haspopup="true"
      @mousedown.prevent
      @click="open = !open"
    >
      <Smile class="h-5 w-5" aria-hidden="true" />
    </button>
    <template v-if="open">
      <div class="fixed inset-0 z-40" @click="open = false" />
      <div
        class="popover absolute bottom-full end-0 z-50 mb-2 grid w-64 grid-cols-8 gap-0.5 p-2"
        role="group"
        :aria-label="t('homeFeed.emoji.label')"
        data-testid="emoji-picker"
      >
        <button
          v-for="e in EMOJIS"
          :key="e"
          type="button"
          class="flex h-7 w-7 items-center justify-center rounded-lg text-lg leading-none transition hover:bg-gray-100 dark:hover:bg-gray-800"
          :aria-label="e"
          @mousedown.prevent
          @click="pick(e)"
        >
          {{ e }}
        </button>
      </div>
    </template>
  </div>
</template>
