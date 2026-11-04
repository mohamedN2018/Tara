<script setup lang="ts">
// An inbox row's second line, bidi-safe: the speaker ("You", a group member)
// sits in its own <bdi> and the text in its own dir="auto" span, while the line
// itself keeps the UI's direction. "ليلى: seen?" can no longer flip to
// "?seen :ليلى" in the English UI. `fallback` shows when there is no message.
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { previewParts } from "@/lib/chat";
import { useDirectoryStore } from "@/stores/directory";
import type { Conversation } from "@/types";

const props = defineProps<{ conversation: Conversation; selfId?: string; fallback?: string }>();
const { t } = useI18n();
const directory = useDirectoryStore();
const parts = computed(() => previewParts(props.conversation, props.selfId, directory.label, t));
</script>

<template>
  <!-- A flex row: an LTR text in the RTL UI (or the reverse) truncates at its own
       end, so "hello from a stranger" never loses its first letters. -->
  <span class="flex min-w-0 items-baseline" data-testid="conversation-preview">
    <template v-if="parts.text">
      <span v-if="parts.who" class="shrink-0 whitespace-pre"><bdi data-testid="preview-who">{{ parts.who }}</bdi>{{ ": " }}</span>
      <span class="min-w-0 truncate" dir="auto" data-testid="preview-text">{{ parts.text }}</span>
    </template>
    <span v-else-if="fallback" class="min-w-0 truncate" dir="auto">{{ fallback }}</span>
  </span>
</template>
