<script setup lang="ts">
import { computed } from "vue";

import { tokenize } from "@/lib/richText";

const props = defineProps<{ body: string }>();
const tokens = computed(() => tokenize(props.body));
</script>

<template>
  <template v-for="(token, i) in tokens" :key="i">
    <a
      v-if="token.kind === 'link'"
      :href="token.href"
      target="_blank"
      rel="noopener noreferrer nofollow ugc"
      class="text-brand-600 hover:underline"
      dir="ltr"
    >{{ token.text }}</a>
    <RouterLink
      v-else-if="token.kind === 'tag'"
      :to="{ name: 'search', query: { q: `#${token.tag}` } }"
      class="font-medium text-brand-600 hover:underline"
    >{{ token.text }}</RouterLink>
    <RouterLink
      v-else-if="token.kind === 'mention'"
      :to="{ name: 'profile', params: { handle: token.handle } }"
      class="font-medium text-brand-600 hover:underline"
      dir="ltr"
    >{{ token.text }}</RouterLink>
    <template v-else>{{ token.text }}</template>
  </template>
</template>
