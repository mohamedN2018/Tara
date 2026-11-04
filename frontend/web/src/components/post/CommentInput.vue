<script setup lang="ts">
import { Send } from "lucide-vue-next";
import { nextTick, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import EmojiPicker from "@/components/post/EmojiPicker.vue";
import MentionField from "@/components/post/MentionField.vue";
import { insertAt } from "@/lib/emojis";

const props = withDefaults(
  defineProps<{ submitting?: boolean; placeholder?: string; autofocus?: boolean }>(),
  { submitting: false, placeholder: "", autofocus: false },
);
const emit = defineEmits<{ submit: [body: string] }>();

const { t } = useI18n();
const body = ref("");
const form = ref<HTMLFormElement | null>(null);
const field = ref<InstanceType<typeof MentionField> | null>(null);

onMounted(() => {
  if (props.autofocus) field.value?.focus();
});

function input(): HTMLInputElement | HTMLTextAreaElement | null {
  return form.value?.querySelector<HTMLInputElement | HTMLTextAreaElement>("input, textarea") ?? null;
}

// The picker keeps focus in the field (mousedown is prevented), so the field's
// selection is where the emoji goes; without one it goes at the end.
async function insertEmoji(emoji: string) {
  const el = input();
  const start = el?.selectionStart ?? body.value.length;
  const end = el?.selectionEnd ?? start;
  const next = insertAt(body.value, emoji, start, end);
  body.value = next.value;
  await nextTick();
  if (!el) return;
  el.focus();
  el.setSelectionRange(next.caret, next.caret);
}

function submit() {
  const value = body.value.trim();
  if (!value || props.submitting) return;
  emit("submit", value);
  body.value = "";
}

defineExpose({ focus: () => field.value?.focus() });
</script>

<template>
  <form ref="form" class="flex items-center gap-1.5" @submit.prevent="submit">
    <MentionField
      ref="field"
      v-model="body"
      field-class="input rounded-full bg-gray-100 dark:bg-gray-800"
      :placeholder="placeholder || t('post.addComment')"
    />
    <EmojiPicker @pick="insertEmoji" />
    <button
      type="submit"
      class="btn-primary rounded-full px-3"
      :disabled="submitting || !body.trim()"
      :aria-label="t('post.comment')"
    >
      <Send class="h-4 w-4 rtl:-scale-x-100" />
    </button>
  </form>
</template>
