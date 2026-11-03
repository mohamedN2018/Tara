<script setup lang="ts">
import { Flag, Heart, MessageCircle, ShieldCheck, Users } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

import TaraLogo from "@/components/brand/TaraLogo.vue";
import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";

const { t } = useI18n();

const features = [
  { icon: Users, title: "landing.features.connectTitle", body: "landing.features.connectBody" },
  { icon: Heart, title: "landing.features.shareTitle", body: "landing.features.shareBody" },
  { icon: Flag, title: "landing.features.belongTitle", body: "landing.features.belongBody" },
  { icon: MessageCircle, title: "landing.features.chatTitle", body: "landing.features.chatBody" },
  { icon: ShieldCheck, title: "landing.features.privacyTitle", body: "landing.features.privacyBody" },
];
</script>

<template>
  <div class="relative min-h-screen overflow-hidden bg-gray-100 dark:bg-gray-950">
    <!-- Ambient brand light -->
    <div aria-hidden="true" class="pointer-events-none absolute inset-0">
      <div class="absolute -top-40 start-1/2 h-[36rem] w-[56rem] -translate-x-1/2 rounded-full bg-brand-600/20 blur-3xl rtl:translate-x-1/2 dark:bg-brand-600/30" />
      <div class="absolute -bottom-40 -end-40 h-[30rem] w-[30rem] rounded-full bg-accent-500/15 blur-3xl" />
    </div>

    <header class="relative mx-auto flex max-w-6xl items-center justify-between px-4 py-5 sm:px-6">
      <TaraLogo :size="34" :label="t('app.name')" />
      <div class="flex items-center gap-2">
        <LocaleToggle />
        <ThemeToggle />
        <RouterLink to="/login" class="btn-ghost hidden sm:inline-flex">{{ t("auth.login") }}</RouterLink>
      </div>
    </header>

    <main class="relative mx-auto max-w-6xl px-4 sm:px-6">
      <section class="flex flex-col items-center pb-16 pt-10 text-center sm:pt-16">
        <div class="relative mb-10">
          <div aria-hidden="true" class="absolute inset-0 scale-150 rounded-full bg-tara-gradient opacity-40 blur-3xl" />
          <TaraLogo variant="icon" :size="112" :label="t('app.name')" class="relative drop-shadow-2xl" />
        </div>

        <p class="mb-4 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-white/70 px-4 py-1.5 text-sm font-semibold text-brand-700 backdrop-blur dark:border-brand-900 dark:bg-gray-900/70 dark:text-brand-300">
          <span class="h-2 w-2 rounded-full bg-accent-500" aria-hidden="true" />
          {{ t("app.tagline") }}
        </p>

        <h1 class="max-w-3xl font-display text-4xl font-extrabold leading-[1.15] tracking-tight text-gray-950 dark:text-white sm:text-6xl">
          {{ t("landing.headline") }}
          <span class="text-gradient">{{ t("landing.headlineAccent") }}</span>
        </h1>
        <p class="mt-6 max-w-2xl text-lg leading-relaxed text-gray-600 dark:text-gray-300">
          {{ t("landing.lead") }}
        </p>

        <div class="mt-10 flex w-full flex-col justify-center gap-3 sm:w-auto sm:flex-row">
          <RouterLink to="/register" class="btn-gradient px-8 py-3.5 text-base">
            {{ t("landing.getStarted") }}
          </RouterLink>
          <RouterLink to="/login" class="btn-outline px-8 py-3.5 text-base">
            {{ t("landing.haveAccount") }}
          </RouterLink>
        </div>
      </section>

      <section class="grid gap-4 pb-20 sm:grid-cols-2 lg:grid-cols-6" :aria-label="t('app.promise')">
        <article
          v-for="(f, i) in features"
          :key="f.title"
          class="card card-hover p-6"
          :class="i < 3 ? 'lg:col-span-2' : 'lg:col-span-3'"
        >
          <span class="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-tara-gradient-soft text-brand-600 ring-1 ring-brand-200/60 dark:text-brand-300 dark:ring-brand-900">
            <component :is="f.icon" class="h-6 w-6" />
          </span>
          <h2 class="text-lg font-bold text-gray-950 dark:text-white">{{ t(f.title) }}</h2>
          <p class="mt-1.5 text-sm leading-relaxed text-gray-600 dark:text-gray-400">{{ t(f.body) }}</p>
        </article>
      </section>
    </main>

    <footer class="relative border-t border-gray-200 py-8 dark:border-gray-800">
      <div class="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-4 text-sm text-gray-500 dark:text-gray-400 sm:flex-row sm:px-6">
        <TaraLogo :size="22" :label="t('app.name')" />
        <p>{{ t("landing.footer") }}</p>
        <p>© 2026</p>
      </div>
    </footer>
  </div>
</template>
