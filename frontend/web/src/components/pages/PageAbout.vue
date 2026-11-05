<script setup lang="ts">
import { Globe, Info, Instagram, Link2, Linkedin, Mail, MapPin, MessageCircle, Music2, Phone, Tag, Twitter, Youtube } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { pageCategoryLabel } from "@/lib/pageCategory";
import { contactHref, PAGE_CONTACT_KEYS, PAGE_LINK_KEYS, type Page } from "@/services/pages";

// The page's intro (side card on Posts) or the About tab: description,
// category, location and the contact links it published. Only http(s) links,
// tel:, mailto: and wa.me become links (`contactHref`).
// `linksApart`: the website and social links show in their own Links card (Posts tab, plan 08).
const props = withDefaults(defineProps<{ page: Page; full?: boolean; linksApart?: boolean }>(), { full: false, linksApart: false });
const i18n = useI18n();
const { t } = i18n;

const ICONS: Record<string, typeof Globe> = {
  website: Globe,
  email: Mail,
  phone: Phone,
  whatsapp: MessageCircle,
  instagram: Instagram,
  x: Twitter,
  linkedin: Linkedin,
  youtube: Youtube,
  tiktok: Music2,
};
const contacts = computed(() =>
  PAGE_CONTACT_KEYS.map((key) => {
    const value = (props.page.contact?.[key] ?? "").trim();
    return { key, value, href: contactHref(key, value) };
  }).filter((c) => c.value && !(props.linksApart && (PAGE_LINK_KEYS as readonly string[]).includes(c.key))),
);
const isEmpty = computed(() => !props.page.description && !props.page.category && !props.page.location && !contacts.value.length);
const shown = (c: { key: string; value: string }) =>
  ["email", "phone", "whatsapp"].includes(c.key) ? c.value : c.value.replace(/^https?:\/\/(www\.)?/i, "").replace(/\/$/, "");
</script>

<template>
  <section class="card space-y-3 p-4" aria-labelledby="page-about-title" data-testid="page-about">
    <h2 id="page-about-title" class="text-xl font-bold">{{ full ? t("pageHub.tabs.about") : t("pageHub.about.title") }}</h2>
    <p v-if="isEmpty" class="text-sm text-gray-500 dark:text-gray-400">{{ t("pageHub.about.noDetails") }}</p>
    <p v-if="page.description" class="whitespace-pre-wrap break-words text-center text-sm sm:text-start" :class="full ? '' : 'border-b border-gray-100 pb-3 dark:border-gray-800'" dir="auto">
      {{ page.description }}
    </p>
    <ul class="space-y-2.5 text-sm">
      <li v-if="page.category" class="flex items-center gap-3">
        <Info class="h-5 w-5 shrink-0 text-gray-400" aria-hidden="true" />
        <span><span class="font-semibold">{{ t("pageHub.about.page") }}</span> · <bdi>{{ pageCategoryLabel(page.category, i18n) }}</bdi></span>
      </li>
      <li v-if="page.location" class="flex items-center gap-3">
        <MapPin class="h-5 w-5 shrink-0 text-gray-400" aria-hidden="true" />
        <span dir="auto">{{ page.location }}</span>
      </li>
    </ul>
    <template v-if="contacts.length">
      <h3 v-if="full" class="pt-1 text-sm font-bold text-gray-600 dark:text-gray-300">{{ t("pageHub.about.contact") }}</h3>
      <ul class="space-y-2.5 text-sm" data-testid="page-contact">
        <li v-for="c in contacts" :key="c.key" class="flex min-w-0 items-center gap-3">
          <component :is="ICONS[c.key] ?? Link2" class="h-5 w-5 shrink-0 text-gray-400" aria-hidden="true" />
          <a
            v-if="c.href"
            :href="c.href"
            class="min-w-0 truncate font-medium text-brand-700 hover:underline dark:text-brand-300"
            dir="ltr"
            :target="c.key === 'email' || c.key === 'phone' ? undefined : '_blank'"
            rel="noopener noreferrer nofollow"
            :aria-label="`${t(`pageHub.about.keys.${c.key}`)}: ${c.value}`"
          >{{ shown(c) }}</a>
          <span v-else class="min-w-0 truncate" dir="ltr">{{ c.value }}</span>
          <span v-if="full" class="ms-auto shrink-0 text-xs text-gray-500 dark:text-gray-400">{{ t(`pageHub.about.keys.${c.key}`) }}</span>
        </li>
      </ul>
    </template>
    <p v-if="full" class="flex items-center gap-3 text-sm text-gray-500 dark:text-gray-400">
      <Tag class="h-5 w-5 shrink-0" aria-hidden="true" /> <span dir="ltr">@{{ page.handle }}</span>
    </p>
  </section>
</template>
