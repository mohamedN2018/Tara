<script setup lang="ts">
// The visitor's front door (decision 5.7): brand and headline on one side, the
// sign-in card on the other, what Tara offers below, and a languages row.
// Signed-in visitors never see it: the route guard sends them to /home.
import { Flag, Heart, MessageCircle, ShieldCheck, Users } from "lucide-vue-next";
import { useI18n } from "vue-i18n";

import LoginCard from "@/components/auth/LoginCard.vue";
import BrandCollage from "@/components/brand/BrandCollage.vue";
import TaraLogo from "@/components/brand/TaraLogo.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";
import type { Locale } from "@/i18n";
import { useUiStore } from "@/stores/ui";

const { t } = useI18n();
const ui = useUiStore();

const features = [
  { icon: Users, title: "landing.features.connectTitle", body: "landing.features.connectBody" },
  { icon: Heart, title: "landing.features.shareTitle", body: "landing.features.shareBody" },
  { icon: Flag, title: "landing.features.belongTitle", body: "landing.features.belongBody" },
  { icon: MessageCircle, title: "landing.features.chatTitle", body: "landing.features.chatBody" },
  { icon: ShieldCheck, title: "landing.features.privacyTitle", body: "landing.features.privacyBody" },
];

// Only the languages Tara ships, each written in itself.
const languages: { code: Locale; name: string }[] = [
  { code: "ar", name: "العربية" },
  { code: "en", name: "English" },
];
</script>

<template>
  <div class="relative flex min-h-screen flex-col overflow-x-hidden bg-gray-100 dark:bg-gray-950">
    <div aria-hidden="true" class="pointer-events-none absolute inset-0 overflow-hidden">
      <div class="absolute -top-48 start-[-10rem] h-[32rem] w-[32rem] rounded-full bg-brand-600/15 blur-3xl dark:bg-brand-600/25" />
      <div class="absolute -bottom-40 end-[-8rem] h-[28rem] w-[28rem] rounded-full bg-accent-500/10 blur-3xl" />
    </div>

    <header class="relative mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-5 sm:px-6">
      <TaraLogo :size="36" :label="t('app.name')" />
      <ThemeToggle />
    </header>

    <main class="relative flex-1">
      <section class="mx-auto grid w-full max-w-6xl items-center gap-10 px-4 pb-14 pt-2 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,25rem)] lg:gap-16 lg:pt-8">
        <div class="min-w-0">
          <div class="mx-auto hidden max-w-lg md:block lg:mx-0">
            <BrandCollage />
          </div>
          <p class="mt-2 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-white/70 px-3.5 py-1 text-sm font-semibold text-brand-700 backdrop-blur dark:border-brand-900 dark:bg-gray-900/70 dark:text-brand-300">
            <span class="h-2 w-2 rounded-full bg-accent-500" aria-hidden="true" />
            {{ t("app.tagline") }}
          </p>
          <h1 class="mt-4 max-w-xl font-display text-4xl font-extrabold leading-[1.15] tracking-tight text-gray-950 dark:text-white sm:text-5xl">
            {{ t("landing.headline") }}
            <span class="text-gradient">{{ t("landing.headlineAccent") }}</span>
          </h1>
          <p class="mt-4 max-w-xl text-base leading-relaxed text-gray-600 dark:text-gray-300 sm:text-lg">
            {{ t("landing.lead") }}
          </p>
        </div>

        <div class="w-full min-w-0">
          <LoginCard :title="t('loginCard.title')" />
          <p class="mt-5 text-center text-sm text-gray-600 dark:text-gray-300">
            <RouterLink to="/pages" class="font-bold text-gray-900 hover:underline dark:text-white">{{ t("loginCard.createPage") }}</RouterLink>
            {{ t("loginCard.createPageHint") }}
          </p>
        </div>
      </section>

      <section class="mx-auto w-full max-w-6xl px-4 pb-16 sm:px-6" aria-labelledby="landing-explore">
        <h2 id="landing-explore" class="mb-5 font-display text-2xl font-bold text-gray-950 dark:text-white">
          {{ t("landing.explore") }}
        </h2>
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-6">
          <article
            v-for="(f, i) in features"
            :key="f.title"
            class="card p-6"
            :class="i < 3 ? 'lg:col-span-2' : 'lg:col-span-3'"
          >
            <span class="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-tara-gradient-soft text-brand-600 ring-1 ring-brand-200/60 dark:text-brand-300 dark:ring-brand-900">
              <component :is="f.icon" class="h-6 w-6" aria-hidden="true" />
            </span>
            <h3 class="text-lg font-bold text-gray-950 dark:text-white">{{ t(f.title) }}</h3>
            <p class="mt-1.5 text-sm leading-relaxed text-gray-600 dark:text-gray-400">{{ t(f.body) }}</p>
          </article>
        </div>
      </section>
    </main>

    <footer class="relative border-t border-gray-200 bg-white/60 py-6 dark:border-gray-800 dark:bg-gray-900/40">
      <div class="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 text-sm text-gray-600 dark:text-gray-400 sm:px-6">
        <nav :aria-label="t('landing.languages')">
          <ul class="flex flex-wrap items-center justify-center gap-x-5 gap-y-2">
            <li v-for="lang in languages" :key="lang.code">
              <button
                type="button"
                :lang="lang.code"
                class="rounded px-1 hover:text-brand-700 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 dark:hover:text-brand-300"
                :class="ui.locale === lang.code ? 'font-bold text-gray-900 dark:text-white' : ''"
                :aria-pressed="ui.locale === lang.code"
                @click="ui.changeLocale(lang.code)"
              >
                {{ lang.name }}
              </button>
            </li>
          </ul>
        </nav>
        <div class="flex flex-col items-center justify-between gap-2 border-t border-gray-200 pt-4 dark:border-gray-800 sm:flex-row">
          <TaraLogo :size="22" :label="t('app.name')" />
          <p class="text-center">{{ t("landing.footer") }}</p>
          <p>© 2026 {{ t("app.name") }}</p>
        </div>
      </div>
    </footer>
  </div>
</template>
