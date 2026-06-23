<script setup lang="ts">
import { Search } from "lucide-vue-next";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

const props = withDefaults(defineProps<{ modelValue?: string; autofocus?: boolean }>(), {
  modelValue: "",
  autofocus: false,
});
const emit = defineEmits<{ "update:modelValue": [v: string]; submit: [v: string] }>();

const { t } = useI18n();
const value = ref(props.modelValue);

watch(
  () => props.modelValue,
  (v) => (value.value = v),
);

function onInput() {
  emit("update:modelValue", value.value);
}
</script>

<template>
  <form class="relative" @submit.prevent="$emit('submit', value)">
    <Search class="pointer-events-none absolute inset-y-0 start-3 my-auto h-4 w-4 text-gray-400" />
    <input
      v-model="value"
      class="input ps-9"
      :placeholder="t('search.placeholder')"
      :autofocus="autofocus"
      @input="onInput"
    />
  </form>
</template>
