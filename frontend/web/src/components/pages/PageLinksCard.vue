<script setup lang="ts">
import { Globe, Instagram, Link2, Linkedin, Music2, Twitter, Youtube } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { contactHref, PAGE_LINK_KEYS, type Page } from "@/services/pages";

// The Posts tab's "Links" card (plan 08): the website and social links the page
// published. Only http(s) links become links (`contactHref`); nothing shows
// when there are none.
const props = defineProps<{ page: Page }>();
const { t } = useI18n();

const ICONS: Record<string, typeof Globe> = {
  website: Globe,
  instagram: Instagram,
  x: Twitter,
  linkedin: Linkedin,
  youtube: Youtube,
  tiktok: Music2,
};
const links = computed(() =>
  PAGE_LINK_KEYS.map((key) => {
    const value = (props.page.contact?.[key] ?? "").trim();
    return { key, value, href: contactHref(key, value) };
  }).filter((l) => l.value && l.href),
);
const shown = (value: string) => value.replace(/^https?:\/\/(www\.)?/i, "").replace(/\/$/, "");
</script>

<template>
  <section v-if="links.length" class="card p-4" aria-labelledby="page-links-title" data-testid="page-links">
    <h2 id="page-links-title" class="mb-3 text-xl font-bold">{{ t("profileTools.page.links") }}</h2>
    <ul class="space-y-2.5 text-sm">
      <li v-for="l in links" :key="l.key" class="flex min-w-0 items-center gap-3">
        <component :is="ICONS[l.key] ?? Link2" class="h-5 w-5 shrink-0 text-gray-500 dark:text-gray-400" aria-hidden="true" />
        <a
          :href="l.href ?? undefined"
          class="min-w-0 truncate font-medium text-brand-700 hover:underline dark:text-brand-300"
          dir="ltr"
          target="_blank"
          rel="noopener noreferrer nofollow"
          :aria-label="`${t(`pageHub.about.keys.${l.key}`)}: ${l.value}`"
        >{{ shown(l.value) }}</a>
      </li>
    </ul>
  </section>
</template>
