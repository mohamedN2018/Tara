<script setup lang="ts">
import { Send } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import MentionField from "@/components/post/MentionField.vue";

const props = withDefaults(
  defineProps<{ submitting?: boolean; placeholder?: string; autofocus?: boolean }>(),
  { submitting: false, placeholder: "", autofocus: false },
);
const emit = defineEmits<{ submit: [body: string] }>();

const { t } = useI18n();
const body = ref("");
const field = ref<InstanceType<typeof MentionField> | null>(null);

onMounted(() => {
  if (props.autofocus) field.value?.focus();
});

function submit() {
  const value = body.value.trim();
  if (!value || props.submitting) return;
  emit("submit", value);
  body.value = "";
}
</script>

<template>
  <form class="flex items-center gap-2" @submit.prevent="submit">
    <MentionField
      ref="field"
      v-model="body"
      field-class="input rounded-full bg-gray-100 dark:bg-gray-800"
      :placeholder="placeholder || t('post.addComment')"
    />
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
