<script setup lang="ts">
import { useI18n } from "vue-i18n";

import { PAGE_CONTACT_KEYS, PAGE_LINK_KEYS, type PageContact } from "@/services/pages";

// Contact inputs (website, email, phone, WhatsApp, social links). Links must be
// http(s); the server checks every value again and drops blanks.
const props = defineProps<{ idPrefix: string; invalid?: string[] }>();
const model = defineModel<PageContact>({ required: true });
const { t } = useI18n();

const isLink = (k: string) => (PAGE_LINK_KEYS as readonly string[]).includes(k);
const typeOf = (k: string) => (k === "email" ? "email" : k === "phone" || k === "whatsapp" ? "tel" : "url");
const pattern = (k: string) => (isLink(k) ? "https?://.+" : undefined);
const bad = (k: string) => props.invalid?.includes(k) ?? false;
function set(k: string, v: string) {
  model.value = { ...model.value, [k]: v };
}
</script>

<template>
  <div class="grid gap-3 sm:grid-cols-2">
    <div v-for="k in PAGE_CONTACT_KEYS" :key="k">
      <label :for="`${idPrefix}-${k}`" class="mb-1 block text-sm font-medium">{{ t(`pageHub.about.keys.${k}`) }}</label>
      <input
        :id="`${idPrefix}-${k}`"
        :value="model[k] ?? ''"
        class="input"
        :class="bad(k) ? 'border-red-500 dark:border-red-500' : ''"
        :type="typeOf(k)"
        dir="ltr"
        maxlength="200"
        :pattern="pattern(k)"
        :placeholder="t(`pageHub.about.placeholders.${k}`)"
        :aria-invalid="bad(k) || undefined"
        :data-testid="`page-contact-${k}`"
        @input="set(k, ($event.target as HTMLInputElement).value)"
      />
    </div>
  </div>
</template>
