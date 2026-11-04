<script setup lang="ts">
import { FileWarning } from "lucide-vue-next";
import { computed, onBeforeUnmount, watchEffect } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import TaraLogo from "@/components/brand/TaraLogo.vue";
import LocaleToggle from "@/components/common/LocaleToggle.vue";
import ThemeToggle from "@/components/common/ThemeToggle.vue";
import { isLegalDoc, LEGAL_IS_DRAFT, LEGAL_VERSIONS, type LegalDocKind, legalPath } from "@/lib/legal";
import { legalDocument } from "@/lib/legalContent";
import { useAuthStore } from "@/stores/auth";

/** `/legal/terms` and `/legal/privacy`: public, bilingual, text from lib/legalContent.ts. */
const { t, locale } = useI18n();
const route = useRoute();
const auth = useAuthStore();

const kind = computed<LegalDocKind>(() => (isLegalDoc(route.params.doc) ? route.params.doc : "terms"));
const other = computed<LegalDocKind>(() => (kind.value === "terms" ? "privacy" : "terms"));
const doc = computed(() => legalDocument(kind.value, locale.value));
const otherDoc = computed(() => legalDocument(other.value, locale.value));
const version = computed(() => LEGAL_VERSIONS[kind.value]);
const year = new Date().getFullYear();

const previousTitle = document.title;
watchEffect(() => {
  document.title = `${doc.value.title} · ${t("app.name")}`;
});
onBeforeUnmount(() => (document.title = previousTitle));
</script>

<template>
  <div class="min-h-screen bg-gray-100 text-gray-900 dark:bg-gray-950 dark:text-gray-100">
    <header class="sticky top-0 z-20 border-b border-gray-200/70 bg-white/90 backdrop-blur-xl dark:border-gray-800/70 dark:bg-gray-950/90">
      <div class="mx-auto flex h-14 max-w-3xl items-center justify-between gap-3 px-4">
        <RouterLink :to="auth.isAuthenticated ? '/home' : '/'" class="flex items-center" :aria-label="t('shell.legal.backHome')">
          <TaraLogo :size="28" :label="t('app.name')" />
        </RouterLink>
        <div class="flex items-center gap-1">
          <LocaleToggle />
          <ThemeToggle />
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-3xl px-4 pb-16 pt-6" data-testid="legal-page" :data-doc="kind">
      <aside
        v-if="LEGAL_IS_DRAFT"
        class="mb-6 flex gap-3 rounded-2xl border border-accent-300 bg-accent-50 p-4 text-accent-900 dark:border-accent-800 dark:bg-accent-900/30 dark:text-accent-100"
        role="note"
        data-testid="legal-draft-banner"
      >
        <FileWarning class="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
        <div>
          <p class="font-bold">{{ t("shell.legal.draftTitle") }}</p>
          <p class="mt-1 text-sm">{{ t("shell.legal.draftBody") }}</p>
        </div>
      </aside>

      <article class="card p-5 sm:p-8">
        <h1 class="font-display text-2xl font-extrabold tracking-tight sm:text-3xl">{{ doc.title }}</h1>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          <span dir="auto">{{ t("shell.legal.version", { version }) }}</span>
        </p>
        <p class="mt-4 leading-relaxed text-gray-700 dark:text-gray-200">{{ doc.intro }}</p>

        <nav class="mt-6 rounded-xl bg-gray-50 p-4 dark:bg-gray-950/60" :aria-label="t('shell.legal.contents')">
          <h2 class="text-sm font-bold">{{ t("shell.legal.contents") }}</h2>
          <ol class="mt-2 grid gap-1 text-sm sm:grid-cols-2">
            <li v-for="s in doc.sections" :key="s.id">
              <a :href="`#${s.id}`" class="text-brand-700 hover:underline dark:text-brand-300">{{ s.heading }}</a>
            </li>
          </ol>
        </nav>

        <section v-for="s in doc.sections" :id="s.id" :key="s.id" class="mt-8 scroll-mt-20">
          <h2 class="text-lg font-bold">{{ s.heading }}</h2>
          <p v-for="(p, i) in s.paragraphs ?? []" :key="`p${i}`" class="mt-3 leading-relaxed text-gray-700 dark:text-gray-200">
            {{ p }}
          </p>
          <ul v-if="s.bullets?.length" class="mt-3 list-disc space-y-1.5 ps-6 leading-relaxed text-gray-700 dark:text-gray-200">
            <li v-for="(b, i) in s.bullets" :key="`b${i}`">{{ b }}</li>
          </ul>
        </section>
      </article>

      <p class="mt-6 text-sm text-gray-600 dark:text-gray-300">
        {{ t("shell.legal.alsoRead") }}:
        <RouterLink :to="legalPath(other)" class="font-semibold text-brand-700 hover:underline dark:text-brand-300" data-testid="legal-other">
          {{ otherDoc.title }}
        </RouterLink>
      </p>
      <p class="mt-2 text-xs text-gray-500 dark:text-gray-400">{{ t("shell.footer.copyright", { name: t("app.name"), year }) }}</p>
    </main>
  </div>
</template>
