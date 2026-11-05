<script setup lang="ts">
// The settings & privacy centre (/settings/:section). Desktop: the section
// navigation in a start column and the section on the right. Mobile: the
// navigation is the index page; a section opens with a back arrow.
import { ArrowLeft, ChevronRight, KeyRound, Lock, MailWarning, Search, ShieldCheck, UserRound } from "lucide-vue-next";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import ResendVerification from "@/components/auth/ResendVerification.vue";
import MessagePrivacySetting from "@/components/chat/MessagePrivacySetting.vue";
import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import NotificationPreferences from "@/components/notifications/NotificationPreferences.vue";
import AccountToggle from "@/components/settings/AccountToggle.vue";
import BirthdayGenderSettings from "@/components/settings/BirthdayGenderSettings.vue";
import ContentPreferences from "@/components/settings/ContentPreferences.vue";
import DeactivateAccount from "@/components/settings/DeactivateAccount.vue";
import DeleteAccount from "@/components/settings/DeleteAccount.vue";
import DisplaySettings from "@/components/settings/DisplaySettings.vue";
import LoginActivity from "@/components/settings/LoginActivity.vue";
import ProfilePrivacySettings from "@/components/settings/ProfilePrivacySettings.vue";
import ProfileQuickEdit from "@/components/settings/ProfileQuickEdit.vue";
import RecognizedDevices from "@/components/settings/RecognizedDevices.vue";
import RelationshipPrivacySettings from "@/components/settings/RelationshipPrivacySettings.vue";
import SearchabilitySetting from "@/components/settings/SearchabilitySetting.vue";
import { isSettingsSection, SECTION_ICON, type SettingsSection } from "@/components/settings/sections";
import SecuritySettings from "@/components/settings/SecuritySettings.vue";
import SettingsNav from "@/components/settings/SettingsNav.vue";
import { entryByKey, MOST_VISITED, searchSettings, type SettingsEntry } from "@/components/settings/settingsIndex";
import TagPrivacySetting from "@/components/settings/TagPrivacySetting.vue";
import TwoFactorSettings from "@/components/settings/TwoFactorSettings.vue";
import { scrollToHashWhenReady } from "@/lib/hashScroll";
import { identityService } from "@/services/identity";
import { useAuthStore } from "@/stores/auth";

const { t, locale } = useI18n();
const route = useRoute();
const auth = useAuthStore();

const section = computed<SettingsSection | null>(() =>
  isSettingsSection(route.params.section) ? route.params.section : null,
);

const displayName = computed(() => auth.profile?.display_name || auth.account?.email?.split("@")[0] || "");
const day = (iso?: string | null) =>
  iso ? new Intl.DateTimeFormat(locale.value, { dateStyle: "medium" }).format(new Date(iso)) : t("settingsCenter.account.never");
const statusLabel = computed(() => {
  const s = auth.account?.status ?? "";
  return ["active", "pending", "suspended", "deactivated", "deleted"].includes(s)
    ? t(`settingsCenter.account.statuses.${s}`)
    : s || "—";
});
// A phone is added through the Telegram bot: offer it only when that is on.
const phoneAvailable = ref(false);
onMounted(async () => {
  phoneAvailable.value = (await identityService.providers()).telegram.enabled;
});
const profileTo = computed(() =>
  auth.profile?.handle ? `/u/${auth.profile.handle}` : auth.account ? `/u/id/${auth.account.id}` : "/home",
);

// A deep link to an anchor (/settings/security#phone): the section's cards
// render after the route resolves, some only after their own fetch, so scroll
// once the anchor exists (lib/hashScroll).
let cancelHashScroll = () => {};
async function scrollToHash() {
  cancelHashScroll();
  if (!route.hash) return;
  await nextTick();
  cancelHashScroll = scrollToHashWhenReady(route.hash);
}
onMounted(scrollToHash);
onBeforeUnmount(() => cancelHashScroll());
watch([section, () => route.hash], scrollToHash, { flush: "post" });

// The landing: one search over every setting (not only the sections), and the
// most visited settings as cards.
const find = ref("");
const found = computed(() => searchSettings(find.value, t));
const mostVisited = MOST_VISITED.map((k) => entryByKey(k)).filter((e): e is SettingsEntry => !!e);

const OVERVIEW_LINKS = [
  { to: "/settings/account#personal-details", key: "personal", icon: UserRound },
  { to: "/settings/security", key: "security", icon: KeyRound },
  { to: "/settings/privacy", key: "privacy", icon: Lock },
] as const;
</script>

<template>
  <AppShell :left="false" :right="false">
    <div class="mx-auto flex w-full max-w-[1180px] gap-6">
      <!-- Start column: the sections (desktop) -->
      <aside
        class="sticky top-20 hidden max-h-[calc(100vh-6rem)] w-[340px] shrink-0 self-start overflow-y-auto rounded-2xl bg-white p-2 shadow-sm ring-1 ring-gray-200/70 lg:block xl:w-[360px] dark:bg-gray-900 dark:ring-gray-800"
      >
        <SettingsNav :active="section" />
      </aside>

      <div class="min-w-0 flex-1">
        <div class="mx-auto w-full max-w-[680px]">
          <!-- Landing: find a setting, and the most visited ones -->
          <section v-if="!section" class="card mb-4 p-4" data-testid="settings-landing">
            <h2 class="text-lg font-bold">{{ t("polish.settings.findTitle") }}</h2>
            <label class="relative mt-3 block">
              <span class="sr-only">{{ t("polish.settings.findLabel") }}</span>
              <Search class="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500 dark:text-gray-400" aria-hidden="true" />
              <input
                v-model="find"
                type="search"
                class="input rounded-full bg-gray-100 ps-10 dark:bg-gray-800"
                dir="auto"
                :placeholder="t('polish.settings.findPlaceholder')"
                aria-controls="settings-find-results"
                data-testid="settings-find"
              />
            </label>
            <div id="settings-find-results" aria-live="polite">
              <ul v-if="found.length" class="mt-2 divide-y divide-gray-100 dark:divide-gray-800" data-testid="settings-find-results">
                <li v-for="e in found" :key="e.key">
                  <RouterLink :to="e.to" class="flex items-center gap-3 rounded-lg p-2 hover:bg-gray-50 dark:hover:bg-gray-800/60" :data-testid="`settings-find-${e.key}`">
                    <component :is="e.icon" class="h-5 w-5 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden="true" />
                    <span class="min-w-0 flex-1">
                      <span class="block text-sm font-semibold">{{ t(`polish.settings.entries.${e.key}.title`) }}</span>
                      <span class="block truncate text-xs text-gray-600 dark:text-gray-400">{{ t(`polish.settings.entries.${e.key}.desc`) }}</span>
                    </span>
                    <ChevronRight class="h-4 w-4 shrink-0 text-gray-400 rtl:rotate-180" aria-hidden="true" />
                  </RouterLink>
                </li>
              </ul>
              <p v-else-if="find.trim()" class="mt-3 text-sm text-gray-600 dark:text-gray-400" data-testid="settings-find-empty">{{ t("settingsCenter.noMatches") }}</p>
            </div>

            <template v-if="!find.trim()">
              <h3 class="mt-4 text-base font-bold">{{ t("polish.settings.mostVisited") }}</h3>
              <ul class="mt-2 grid gap-2 sm:grid-cols-2" data-testid="settings-most-visited">
                <li v-for="e in mostVisited" :key="e.key">
                  <RouterLink
                    :to="e.to"
                    class="flex h-full items-start gap-3 rounded-xl p-3 ring-1 ring-gray-200 transition hover:bg-gray-50 dark:ring-gray-800 dark:hover:bg-gray-800/60"
                    :data-testid="`settings-most-${e.key}`"
                  >
                    <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-200">
                      <component :is="e.icon" class="h-5 w-5" aria-hidden="true" />
                    </span>
                    <span class="min-w-0 flex-1">
                      <span class="block text-sm font-semibold">{{ t(`polish.settings.entries.${e.key}.title`) }}</span>
                      <span class="block text-xs text-gray-600 dark:text-gray-400">{{ t(`polish.settings.entries.${e.key}.desc`) }}</span>
                    </span>
                  </RouterLink>
                </li>
              </ul>
            </template>
          </section>

          <!-- Mobile index: the navigation is the page -->
          <div v-if="!section" class="mb-4 rounded-2xl bg-white p-2 shadow-sm ring-1 ring-gray-200/70 lg:hidden dark:bg-gray-900 dark:ring-gray-800">
            <SettingsNav :active="null" />
          </div>

          <!-- Account centre summary (no section chosen, desktop) -->
          <section v-if="!section" class="card mb-4 hidden p-5 lg:block" data-testid="settings-overview">
            <h2 class="text-xl font-bold">{{ t("settingsCenter.overview.title") }}</h2>
            <p class="mt-1 text-sm text-gray-600 dark:text-gray-300">{{ t("settingsCenter.overview.lead") }}</p>
            <div class="mt-4 flex items-center gap-3 rounded-xl bg-gray-50 p-3 dark:bg-gray-800/60">
              <UserAvatar :name="displayName || '?'" :media-id="auth.profile?.avatar_media_id" :size="48" />
              <span class="min-w-0">
                <span class="block truncate font-semibold" dir="auto">{{ displayName }}</span>
                <span class="block truncate text-sm text-gray-500 dark:text-gray-400" dir="ltr">{{ auth.account?.email }}</span>
              </span>
            </div>
            <ul class="mt-3 space-y-1 text-sm">
              <li v-if="auth.account && !auth.account.email_verified" class="flex items-center gap-2 text-amber-700 dark:text-amber-300">
                <MailWarning class="h-4 w-4" aria-hidden="true" />{{ t("settingsCenter.overview.unverified") }}
              </li>
              <li class="flex items-center gap-2">
                <ShieldCheck class="h-4 w-4" :class="auth.account?.two_factor_enabled ? 'text-green-600' : 'text-gray-400'" aria-hidden="true" />
                {{ auth.account?.two_factor_enabled ? t("settingsCenter.overview.twoFactorOn") : t("settingsCenter.overview.twoFactorOff") }}
              </li>
            </ul>
            <div class="mt-4 grid gap-2 sm:grid-cols-3">
              <RouterLink
                v-for="l in OVERVIEW_LINKS"
                :key="l.key"
                :to="l.to"
                class="flex items-center gap-2 rounded-xl p-3 text-sm font-semibold ring-1 ring-gray-200 transition hover:bg-gray-50 dark:ring-gray-800 dark:hover:bg-gray-800/60"
              >
                <component :is="l.icon" class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" />
                <span class="flex-1">{{ t(`settingsCenter.overview.${l.key}`) }}</span>
                <ChevronRight class="h-4 w-4 text-gray-400 rtl:rotate-180" aria-hidden="true" />
              </RouterLink>
            </div>
          </section>

          <template v-if="section">
            <div class="mb-4 flex items-center gap-2">
              <RouterLink to="/settings" class="icon-btn h-9 w-9 lg:hidden" :aria-label="t('settingsCenter.back')" data-testid="settings-back">
                <ArrowLeft class="h-5 w-5 rtl:rotate-180" aria-hidden="true" />
              </RouterLink>
              <component :is="SECTION_ICON[section]" class="hidden h-6 w-6 text-brand-600 lg:block dark:text-brand-300" aria-hidden="true" />
              <h1 class="text-xl font-bold" data-testid="settings-section-title">{{ t(`settingsCenter.sections.${section}.title`) }}</h1>
            </div>

            <!-- A: Account centre -->
            <template v-if="section === 'account'">
              <section id="personal-details" class="card mb-4 scroll-mt-20 p-4" data-testid="account-details">
                <h2 class="mb-3 font-semibold">{{ t("settingsCenter.account.personal") }}</h2>
                <dl class="divide-y divide-gray-100 text-sm dark:divide-gray-800">
                  <div class="flex items-center justify-between gap-3 py-2">
                    <dt class="text-gray-500 dark:text-gray-400">{{ t("settingsCenter.account.name") }}</dt>
                    <dd class="flex min-w-0 items-center gap-2">
                      <span class="truncate font-medium" dir="auto">{{ displayName || "—" }}</span>
                      <RouterLink :to="profileTo" class="shrink-0 text-xs font-semibold text-brand-700 hover:underline dark:text-brand-300">
                        {{ t("settingsCenter.account.editProfile") }}
                      </RouterLink>
                    </dd>
                  </div>
                  <div v-if="auth.profile?.handle" class="flex items-center justify-between gap-3 py-2">
                    <dt class="text-gray-500 dark:text-gray-400">{{ t("settingsCenter.account.handle") }}</dt>
                    <dd class="truncate font-medium" dir="ltr">{{ "@" + auth.profile.handle }}</dd>
                  </div>
                  <div class="flex flex-wrap items-center justify-between gap-3 py-2">
                    <dt class="text-gray-500 dark:text-gray-400">{{ t("settingsCenter.account.email") }}</dt>
                    <dd class="flex min-w-0 flex-wrap items-center justify-end gap-2">
                      <span class="truncate font-medium" dir="ltr">{{ auth.account?.email || "—" }}</span>
                      <span
                        class="shrink-0 rounded-full px-2 py-0.5 text-xs font-medium"
                        :class="auth.account?.email_verified
                          ? 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300'
                          : 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300'"
                      >
                        {{ auth.account?.email_verified ? t("settings.verified") : t("settings.unverified") }}
                      </span>
                      <ResendVerification v-if="auth.account && !auth.account.email_verified" :email="auth.account.email" compact />
                    </dd>
                  </div>
                  <div class="flex items-center justify-between gap-3 py-2">
                    <dt class="text-gray-500 dark:text-gray-400">{{ t("settingsCenter.account.phone") }}</dt>
                    <dd class="truncate font-medium" dir="ltr">
                      <template v-if="auth.account?.phone">{{ auth.account.phone }}</template>
                      <RouterLink
                        v-else-if="phoneAvailable"
                        to="/settings/security#phone"
                        class="text-xs font-semibold text-brand-700 hover:underline dark:text-brand-300"
                        dir="auto"
                        data-testid="account-add-phone"
                      >
                        {{ t("settingsCenter.account.addPhone") }}
                      </RouterLink>
                      <span v-else class="text-gray-500 dark:text-gray-400" dir="auto">{{ t("settingsCenter.account.noPhone") }}</span>
                    </dd>
                  </div>
                  <div class="flex items-center justify-between gap-3 py-2">
                    <dt class="text-gray-500 dark:text-gray-400">{{ t("settingsCenter.account.status") }}</dt>
                    <dd class="font-medium" data-testid="account-status">{{ statusLabel }}</dd>
                  </div>
                  <div class="flex items-center justify-between gap-3 py-2">
                    <dt class="text-gray-500 dark:text-gray-400">{{ t("settingsCenter.account.memberSince") }}</dt>
                    <dd class="font-medium">{{ day(auth.account?.created_at) }}</dd>
                  </div>
                  <div class="flex items-center justify-between gap-3 py-2">
                    <dt class="text-gray-500 dark:text-gray-400">{{ t("settingsCenter.account.lastLogin") }}</dt>
                    <dd class="font-medium">{{ day(auth.account?.last_login_at) }}</dd>
                  </div>
                </dl>
              </section>
              <BirthdayGenderSettings />
              <ProfileQuickEdit />
              <DeactivateAccount />
              <DeleteAccount />
            </template>

            <!-- B: Privacy -->
            <template v-else-if="section === 'privacy'">
              <ProfilePrivacySettings />
              <!-- Who can find you: people-search visibility (fix track C). -->
              <SearchabilitySetting />
              <MessagePrivacySetting />
              <RelationshipPrivacySettings />
              <TagPrivacySetting />
              <section id="active-status" class="card mb-4 scroll-mt-20 p-4" data-testid="active-status">
                <h2 class="mb-1 font-semibold">{{ t("settingsCenter.privacy.activeStatus") }}</h2>
                <AccountToggle
                  field="show_presence"
                  :label="t('settingsCenter.privacy.showActive')"
                  :hint="t('settingsCenter.privacy.showActiveHint')"
                  :saved-text="t('settingsCenter.privacy.saved')"
                />
              </section>
              <section class="card mb-4 divide-y divide-gray-100 p-2 dark:divide-gray-800">
                <RouterLink to="/settings/account#personal" class="flex items-center gap-3 rounded-lg p-2 hover:bg-gray-50 dark:hover:bg-gray-800/60">
                  <span class="min-w-0 flex-1">
                    <span class="block text-sm font-semibold">{{ t("settingsCenter.privacy.personalLink") }}</span>
                    <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t("settingsCenter.privacy.personalLinkDesc") }}</span>
                  </span>
                  <ChevronRight class="h-4 w-4 text-gray-400 rtl:rotate-180" aria-hidden="true" />
                </RouterLink>
                <RouterLink to="/settings/content#blocks" class="flex items-center gap-3 rounded-lg p-2 hover:bg-gray-50 dark:hover:bg-gray-800/60">
                  <span class="min-w-0 flex-1">
                    <span class="block text-sm font-semibold">{{ t("settingsCenter.privacy.contentLink") }}</span>
                    <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t("settingsCenter.privacy.contentLinkDesc") }}</span>
                  </span>
                  <ChevronRight class="h-4 w-4 text-gray-400 rtl:rotate-180" aria-hidden="true" />
                </RouterLink>
              </section>
            </template>

            <!-- C: Password and security -->
            <template v-else-if="section === 'security'">
              <SecuritySettings />
              <TwoFactorSettings />
              <section id="login-alerts" class="card mb-4 scroll-mt-20 p-4" data-testid="login-alerts">
                <h2 class="mb-1 font-semibold">{{ t("settingsCenter.loginAlerts.title") }}</h2>
                <AccountToggle field="login_alerts" :label="t('settingsCenter.loginAlerts.label')" :saved-text="t('settingsCenter.privacy.saved')" />
              </section>
              <RecognizedDevices />
              <LoginActivity />
            </template>

            <!-- D: Notifications (the notification service's preferences) -->
            <section v-else-if="section === 'notifications'" id="notifications" class="card mb-4 scroll-mt-20 p-4">
              <NotificationPreferences />
            </section>

            <!-- E: Feed and content preferences -->
            <ContentPreferences v-else-if="section === 'content'" />

            <!-- F: Display and accessibility -->
            <DisplaySettings v-else-if="section === 'display'" />
          </template>
        </div>
      </div>
    </div>
  </AppShell>
</template>
