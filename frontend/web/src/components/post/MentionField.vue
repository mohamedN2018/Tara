<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from "vue";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { mentionAtCaret } from "@/lib/richText";
import { searchService } from "@/services/search";
import { useDirectoryStore } from "@/stores/directory";

const props = withDefaults(
  defineProps<{
    modelValue: string;
    multiline?: boolean;
    fieldClass?: string;
    placeholder?: string;
    label?: string;
  }>(),
  { multiline: false, fieldClass: "", placeholder: "", label: "" },
);
const emit = defineEmits<{ "update:modelValue": [value: string] }>();

interface Candidate {
  id: string;
  handle: string;
}

const DEBOUNCE_MS = 150;
const directory = useDirectoryStore();
const field = ref<HTMLInputElement | HTMLTextAreaElement | null>(null);
const candidates = ref<Candidate[]>([]);
const active = ref(0);
let mention: { query: string; start: number } | null = null;
let timer: number | undefined;
let generation = 0;

const open = computed(() => candidates.value.length > 0);

function close() {
  window.clearTimeout(timer);
  generation++;
  candidates.value = [];
  active.value = 0;
  mention = null;
}

async function search(query: string, current: number) {
  try {
    const hits = await searchService.suggest(query);
    if (current !== generation) return;
    // Hits carry the handle; older indexes only titled a user "handle display name".
    candidates.value = hits
      .filter((h) => h.type === "user")
      .slice(0, 6)
      .map((h) => ({ id: h.id, handle: h.handle || h.title.split(" ")[0] }));
    active.value = 0;
  } catch {
    candidates.value = [];
  }
}

function onInput(event: Event) {
  const el = event.target as HTMLInputElement;
  emit("update:modelValue", el.value);
  mention = mentionAtCaret(el.value, el.selectionStart ?? el.value.length);
  window.clearTimeout(timer);
  const current = ++generation;
  if (!mention) {
    candidates.value = [];
    return;
  }
  const { query } = mention;
  timer = window.setTimeout(() => void search(query, current), DEBOUNCE_MS);
}

async function pick(candidate: Candidate) {
  const el = field.value;
  if (!el || !mention) return;
  const end = mention.start + mention.query.length + 1;
  const inserted = `@${candidate.handle} `;
  const value = props.modelValue.slice(0, mention.start) + inserted + props.modelValue.slice(end);
  const caret = mention.start + inserted.length;
  emit("update:modelValue", value);
  close();
  await nextTick();
  el.focus();
  el.setSelectionRange(caret, caret);
}

function onKeydown(event: KeyboardEvent) {
  if (!open.value) return;
  const size = candidates.value.length;
  if (event.key === "ArrowDown") active.value = (active.value + 1) % size;
  else if (event.key === "ArrowUp") active.value = (active.value + size - 1) % size;
  else if (event.key === "Enter" || event.key === "Tab") void pick(candidates.value[active.value]);
  else if (event.key === "Escape") close();
  else return;
  event.preventDefault();
}

onBeforeUnmount(close);
defineExpose({ focus: () => field.value?.focus() });
</script>

<template>
  <div class="relative min-w-0 flex-1">
    <component
      :is="multiline ? 'textarea' : 'input'"
      ref="field"
      :value="modelValue"
      :class="fieldClass"
      :placeholder="placeholder"
      :aria-label="label || placeholder"
      :aria-expanded="open"
      autocomplete="off"
      dir="auto"
      @input="onInput"
      @keydown="onKeydown"
      @blur="close"
    />
    <ul
      v-if="open"
      class="popover absolute inset-x-0 top-full z-50 mt-1 max-h-60 overflow-y-auto p-1"
      role="listbox"
      data-testid="mention-list"
    >
      <li v-for="(c, i) in candidates" :key="c.id" role="option" :aria-selected="i === active">
        <button
          type="button"
          class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-start text-sm"
          :class="i === active ? 'bg-gray-100 dark:bg-gray-800' : ''"
          @mousedown.prevent="pick(c)"
        >
          <UserAvatar :name="directory.label(c.id)" :media-id="directory.avatarOf(c.id)" :size="28" />
          <span class="min-w-0 truncate" dir="auto">{{ directory.label(c.id) }}</span>
          <span class="ms-auto text-xs text-gray-500 dark:text-gray-400" dir="ltr">@{{ c.handle }}</span>
        </button>
      </li>
    </ul>
  </div>
</template>
