<script setup lang="ts">
import { Send } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

const emit = defineEmits<{ send: [body: string]; typing: [] }>();

const { t } = useI18n();
const body = ref("");

function submit() {
  const text = body.value.trim();
  if (!text) return;
  emit("send", text);
  body.value = "";
}
</script>

<template>
  <form
    class="flex items-center gap-2 border-t border-gray-200 p-3 dark:border-gray-800"
    @submit.prevent="submit"
  >
    <input
      v-model="body"
      class="input"
      :placeholder="t('messages.placeholder')"
      @input="$emit('typing')"
    />
    <button type="submit" class="btn-primary px-3" :disabled="!body.trim()">
      <Send class="h-4 w-4" />
    </button>
  </form>
</template>
