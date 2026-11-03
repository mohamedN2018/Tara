<script setup lang="ts">
import { MessageCircle, ShieldCheck, Users } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

import TaraLogo from "@/components/brand/TaraLogo.vue";
import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";

defineProps<{ title: string; centered?: boolean }>();

const { t } = useI18n();

const points = [
  { icon: Users, title: "landing.features.connectTitle", body: "landing.features.connectBody" },
  { icon: MessageCircle, title: "landing.features.chatTitle", body: "landing.features.chatBody" },
  { icon: ShieldCheck, title: "landing.features.privacyTitle", body: "landing.features.privacyBody" },
];
</script>

<template>
  <div class="grid min-h-screen bg-gray-100 dark:bg-gray-950 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
    <!-- Brand panel (desktop) -->
    <aside class="relative m-3 hidden overflow-hidden rounded-3xl bg-ink p-10 text-white lg:flex lg:flex-col xl:p-14">
      <div aria-hidden="true" class="pointer-events-none absolute inset-0">
        <div class="absolute -end-24 -top-24 h-96 w-96 rounded-full bg-brand-600/50 blur-3xl" />
        <div class="absolute -bottom-32 -start-16 h-[26rem] w-[26rem] rounded-full bg-accent-500/25 blur-3xl" />
        <div class="absolute end-10 top-1/3 h-56 w-56 rounded-full bg-brand-400/25 blur-3xl" />
        <svg class="absolute inset-0 h-full w-full opacity-[0.07]" aria-hidden="true">
          <defs>
            <pattern id="auth-grid" width="32" height="32" patternUnits="userSpaceOnUse">
              <path d="M32 0H0V32" fill="none" stroke="white" stroke-width="1" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#auth-grid)" />
        </svg>
      </div>

      <RouterLink to="/" class="relative self-start">
        <TaraLogo :size="40" tone="white" :label="t('app.name')" />
      </RouterLink>

      <div class="relative mt-auto max-w-md">
        <p class="font-display text-4xl font-extrabold leading-tight xl:text-5xl">
          <span class="bg-gradient-to-l from-accent-300 via-brand-300 to-white bg-clip-text text-transparent rtl:bg-gradient-to-r">{{ t("app.tagline") }}</span>
        </p>
        <p class="mt-4 text-lg text-white/70">{{ t("app.promise") }}</p>

        <ul class="mt-10 space-y-4">
          <li v-for="p in points" :key="p.title" class="flex items-start gap-4">
            <span class="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white/10 ring-1 ring-white/15 backdrop-blur">
              <component :is="p.icon" class="h-5 w-5 text-brand-200" />
            </span>
            <span>
              <span class="block font-bold">{{ t(p.title) }}</span>
              <span class="block text-sm text-white/60">{{ t(p.body) }}</span>
            </span>
          </li>
        </ul>
      </div>
      <p class="relative mt-12 text-xs text-white/40">© 2026 {{ t("app.name") }}</p>
    </aside>

    <!-- Form side -->
    <main class="relative flex min-h-screen flex-col px-4 py-6 sm:px-8">
      <div class="flex items-center justify-between">
        <RouterLink to="/" class="lg:invisible">
          <TaraLogo :size="32" :label="t('app.name')" />
        </RouterLink>
        <div class="flex items-center gap-2">
          <LocaleToggle />
          <ThemeToggle />
        </div>
      </div>

      <div class="flex flex-1 items-center justify-center py-10">
        <div class="w-full max-w-[26rem]" :class="centered ? 'text-center' : ''">
          <h1 class="font-display text-3xl font-extrabold tracking-tight text-gray-950 dark:text-white">{{ title }}</h1>
          <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">{{ t("app.tagline") }}</p>
          <div class="mt-8">
            <slot />
          </div>
        </div>
      </div>
    </main>
  </div>
</template>
