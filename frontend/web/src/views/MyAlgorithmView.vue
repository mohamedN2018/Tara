<script setup lang="ts">
// Settings > Content preferences > My Algorithm (Tara Intelligence 04 WP 8.2; 07 WP 8.4-B2,
// 8.5-B2, 8.7-B2). Every control reads and writes feed's real preferences
// (`/feed/preferences/`): each change is a PATCH with the version read (a 409 means another
// window changed it: reload and say so) and an undo toast (`POST preferences/undo/`).
// Frequency and the discovery switches are two separate groups. Location is not here (R5).
import type { AxiosError } from "axios";
import { Clock3, EyeOff, Heart, Languages, Layers, RotateCcw, Search, ShieldCheck, SlidersHorizontal, Sparkles, Star, UserX, VolumeX } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import InterestProfile from "@/components/feed/InterestProfile.vue";
import AppShell from "@/components/layout/AppShell.vue";
import SettingSwitch from "@/components/settings/SettingSwitch.vue";
import { httpStatus } from "@/lib/api";
import { retryAfterMs } from "@/lib/homeRefresh";
import { setPersonalizationOff } from "@/lib/signals";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { useRelationshipPrefs } from "@/lib/useRelationshipPrefs";
import {
  CONTENT_LANGUAGES,
  DISCOVERY_LEVELS,
  DISCOVERY_PREFS,
  type DiscoveryPref,
  FEED_FORMATS,
  FEED_MODES,
  type FeedFormat,
  type FeedMode,
  type FeedPreferences,
  type FeedPreferencesPatch,
  feedService,
  type FormatChoice,
  type InterestProfile as Profile,
  type ResetPreview,
} from "@/services/feed";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

const { t, te, locale } = useI18n();
const toasts = useToastStore();
const directory = useDirectoryStore();
const people = useRelationshipPrefs();

const prefs = ref<FeedPreferences | null>(null);
const profile = ref<Profile | null>(null);
const loading = ref(true);
const failed = ref(false);
const saving = ref(false);

async function loadPrefs() {
  const p = await feedService.preferences();
  prefs.value = p;
  setPersonalizationOff(p.personalization_off === true);
}
async function loadProfile() {
  try {
    profile.value = await feedService.interestProfile();
  } catch {
    profile.value = null;
  }
}
async function load() {
  loading.value = true;
  failed.value = false;
  try {
    await Promise.all([loadPrefs(), loadProfile(), people.ensure(["favorites"])]);
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}
onMounted(load);

// A server that predates R4 sends only the mode: those sections stay hidden.
const full = computed(() => !!prefs.value && "personalization_off" in prefs.value);

/** One change: PATCH with the version, then an undo toast; 409 reloads and says so. */
async function save(patch: FeedPreferencesPatch) {
  if (!prefs.value || saving.value) return;
  saving.value = true;
  try {
    const next = await feedService.updatePreferences(patch, prefs.value.version);
    prefs.value = next;
    if ("personalization_off" in patch) setPersonalizationOff(next.personalization_off === true);
    const changeId = next.change_id;
    toasts.push(
      {
        text: t("myAlgorithm.toast.saved"),
        icon: "success",
        action: changeId ? { label: t("myAlgorithm.toast.undo"), testid: "pref-undo", run: () => void undo(changeId) } : undefined,
      },
      8000,
    );
  } catch (e) {
    if (httpStatus(e) === 409) {
      await loadPrefs().catch(() => undefined);
      toasts.push({ text: t("myAlgorithm.toast.stale"), icon: "error" }, 6000);
    } else toasts.error(e);
  } finally {
    saving.value = false;
  }
}

async function undo(changeId: string) {
  try {
    const back = await feedService.undoPreference(changeId);
    prefs.value = back;
    setPersonalizationOff(back.personalization_off === true);
    toasts.success(t("myAlgorithm.toast.undone"));
  } catch (e) {
    if (httpStatus(e) === 409) await loadPrefs().catch(() => undefined);
    toasts.error(e);
  }
}

// ---- controls ----
const mode = computed(() => prefs.value?.default_mode ?? null);
const setMode = (m: FeedMode) => m !== mode.value && save({ default_mode: m });

const formatOf = (f: FeedFormat): FormatChoice | "normal" => prefs.value?.formats?.[f] ?? "normal";
function setFormat(f: FeedFormat, choice: FormatChoice | "normal") {
  if (choice === formatOf(f)) return;
  const next = { ...(prefs.value?.formats ?? {}) };
  if (choice === "normal") delete next[f];
  else next[f] = choice;
  void save({ formats: next });
}

const level = computed(() => prefs.value?.discovery_level ?? null);
const setLevel = (n: number) => n !== level.value && save({ discovery_level: n });

const discoveryOn = (k: DiscoveryPref) => prefs.value?.discovery_prefs?.[k] !== false;
const setDiscovery = (k: DiscoveryPref, on: boolean) => save({ discovery_prefs: { ...(prefs.value?.discovery_prefs ?? {}), [k]: on } });

const languages = computed(() => prefs.value?.languages ?? []);
function toggleLanguage(code: string) {
  const has = languages.value.includes(code);
  void save({ languages: has ? languages.value.filter((l) => l !== code) : [...languages.value, code] });
}

// ---- interests, muted topics, hidden creators ----
const muted = computed(() => profile.value?.muted_topics ?? []);
const hidden = computed(() => profile.value?.hidden_creators ?? []);
const rowLabel = (r: { slug: string; label_ar?: string; label_en?: string }) =>
  (locale.value === "ar" ? r.label_ar : r.label_en) || r.label_en || r.label_ar || r.slug;
const busyRow = ref<string | null>(null);
async function unmute(key: string) {
  busyRow.value = `topic:${key}`;
  try {
    await feedService.deleteInterest("topic", key);
    toasts.success(t("myAlgorithm.page.muted.unmuted"));
    await loadProfile();
  } catch (e) {
    toasts.error(e);
  } finally {
    busyRow.value = null;
  }
}
async function unhide(accountId: string) {
  busyRow.value = `creator:${accountId}`;
  try {
    await feedService.deleteInterest("creator", accountId);
    toasts.success(t("myAlgorithm.page.hidden.unhidden", { name: directory.label(accountId) }));
    await loadProfile();
  } catch (e) {
    toasts.error(e);
  } finally {
    busyRow.value = null;
  }
}
const favorites = computed(() => (people.loaded("favorites") ? people.list("favorites") : []));

// ---- support explain consent (decision 17) ----
const consentUntil = computed(() => {
  const at = prefs.value?.debug_consent_expires_at;
  return at && new Date(at).getTime() > Date.now() ? at : null;
});
const when = (iso: string) => {
  try {
    return new Date(iso).toLocaleString(locale.value, { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return iso;
  }
};
async function grantConsent() {
  saving.value = true;
  try {
    const granted = await feedService.grantDebugConsent();
    if (granted?.expires_at && prefs.value) prefs.value = { ...prefs.value, debug_consent_expires_at: granted.expires_at };
    await loadPrefs().catch(() => undefined);
    toasts.success(t("myAlgorithm.page.consent.granted"));
  } catch (e) {
    toasts.error(e);
  } finally {
    saving.value = false;
  }
}
async function revokeConsent() {
  saving.value = true;
  try {
    await feedService.revokeDebugConsent();
    await loadPrefs();
    toasts.success(t("myAlgorithm.page.consent.revoked"));
  } catch (e) {
    toasts.error(e);
  } finally {
    saving.value = false;
  }
}

// ---- reset (two steps, not undoable) ----
const preview = ref<ResetPreview | null>(null);
const resetBusy = ref(false);
const resetError = ref("");
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
useEscapeKey(
  computed(() => !!preview.value),
  () => (preview.value = null),
);
const itemLabel = (key: string) =>
  te(`myAlgorithm.page.reset.items.${key}`) ? t(`myAlgorithm.page.reset.items.${key}`) : t("myAlgorithm.page.reset.items.other");
const uniqueLabels = (keys: string[]) => [...new Set(keys.map(itemLabel))];
const nextAllowed = computed(() => {
  const at = prefs.value?.reset_available_at;
  return at && new Date(at).getTime() > Date.now() ? at : null;
});
function tooSoon(e: unknown) {
  const ms = retryAfterMs((e as AxiosError)?.response?.headers?.["retry-after"]);
  const at = ms != null ? new Date(Date.now() + ms).toISOString() : (nextAllowed.value ?? null);
  resetError.value = at ? t("myAlgorithm.page.reset.tooSoon", { time: when(at) }) : t("errors.rate_limited");
}
async function startReset() {
  if (resetBusy.value) return;
  resetBusy.value = true;
  resetError.value = "";
  try {
    preview.value = await feedService.resetPreview();
  } catch (e) {
    if (httpStatus(e) === 429) tooSoon(e);
    else toasts.error(e);
  } finally {
    resetBusy.value = false;
  }
}
async function confirmReset() {
  if (!preview.value || resetBusy.value) return;
  resetBusy.value = true;
  try {
    const done = await feedService.resetConfirm(preview.value.confirm_token);
    preview.value = null;
    if (prefs.value) prefs.value = { ...prefs.value, reset_at: done.reset_at, reset_available_at: done.next_allowed_at };
    // The reset changes the row (and its version): read it again before the next PATCH.
    await loadPrefs().catch(() => undefined);
    toasts.success(t("myAlgorithm.page.reset.done"));
    await loadProfile();
  } catch (e) {
    const status = httpStatus(e);
    if (status === 429) {
      preview.value = null;
      tooSoon(e);
    } else if (status === 400 || status === 410) {
      preview.value = null;
      resetError.value = t("myAlgorithm.page.reset.expired");
    } else toasts.error(e);
  } finally {
    resetBusy.value = false;
  }
}

const sectionCls = "card p-4 sm:p-5";
const segBtn = (on: boolean) =>
  [
    "rounded-lg px-3 py-1.5 text-sm font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 disabled:opacity-60",
    on ? "bg-brand-600 text-white" : "bg-gray-100 text-gray-700 hover:bg-brand-50 hover:text-brand-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-brand-950/60",
  ].join(" ");
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[720px] space-y-4" data-testid="my-algorithm">
      <header class="px-1">
        <h1 class="text-2xl font-bold">{{ t("myAlgorithm.page.title") }}</h1>
        <p class="text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.hint") }}</p>
      </header>

      <p v-if="loading" class="card p-4 text-sm text-gray-500 dark:text-gray-400" role="status">{{ t("myAlgorithm.page.loading") }}</p>
      <p v-else-if="failed || !prefs" class="card p-4 text-sm text-red-600 dark:text-red-400" role="alert">
        {{ t("myAlgorithm.page.failed") }}
        <button type="button" class="ms-2 font-semibold underline" @click="load">{{ t("states.retry") }}</button>
      </p>

      <template v-else>
        <p v-if="prefs.personalization_off" class="rounded-xl bg-brand-50 p-3 text-sm text-brand-800 dark:bg-brand-950/60 dark:text-brand-200" role="status" data-testid="personalization-off-note">
          {{ t("myAlgorithm.page.personalization.offNote") }}
        </p>

        <!-- Home mode -->
        <section :class="sectionCls" aria-labelledby="ma-mode" data-testid="ma-mode">
          <h2 id="ma-mode" class="flex items-center gap-2 text-[15px] font-bold"><Layers class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("myAlgorithm.page.mode.title") }}</h2>
          <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.mode.hint") }}</p>
          <div class="mt-3 flex flex-wrap gap-2" role="radiogroup" :aria-labelledby="'ma-mode'">
            <button
              v-for="m in FEED_MODES"
              :key="m"
              type="button"
              role="radio"
              :aria-checked="mode === m"
              :class="segBtn(mode === m)"
              :disabled="saving"
              :data-testid="`ma-mode-${m}`"
              @click="setMode(m)"
            >
              {{ t(`homeFeed.modes.${m}`) }}
            </button>
          </div>
        </section>

        <template v-if="full">
          <!-- Formats -->
          <section :class="sectionCls" aria-labelledby="ma-formats" data-testid="ma-formats">
            <h2 id="ma-formats" class="flex items-center gap-2 text-[15px] font-bold"><SlidersHorizontal class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("myAlgorithm.page.formats.title") }}</h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.formats.hint") }}</p>
            <ul class="mt-2 divide-y divide-gray-100 dark:divide-gray-800">
              <li v-for="f in FEED_FORMATS" :key="f" class="flex flex-wrap items-center justify-between gap-2 py-2">
                <span :id="`ma-format-${f}`" class="text-sm font-medium">{{ t(`myAlgorithm.page.formats.names.${f}`) }}</span>
                <div class="flex gap-1" role="radiogroup" :aria-labelledby="`ma-format-${f}`">
                  <button
                    v-for="c in ['less', 'normal', 'more'] as const"
                    :key="c"
                    type="button"
                    role="radio"
                    :aria-checked="formatOf(f) === c"
                    :class="segBtn(formatOf(f) === c)"
                    :disabled="saving"
                    :data-testid="`ma-format-${f}-${c}`"
                    @click="setFormat(f, c)"
                  >
                    {{ t(`myAlgorithm.page.formats.${c}`) }}
                  </button>
                </div>
              </li>
            </ul>
          </section>

          <!-- Recommendation frequency (its own group, decision: 04 WP 8.2) -->
          <section :class="sectionCls" aria-labelledby="ma-frequency" data-testid="ma-frequency">
            <h2 id="ma-frequency" class="flex items-center gap-2 text-[15px] font-bold"><Sparkles class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("myAlgorithm.page.frequency.title") }}</h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.frequency.hint") }}</p>
            <div class="mt-3 flex flex-wrap gap-2" role="radiogroup" aria-labelledby="ma-frequency">
              <button
                v-for="n in DISCOVERY_LEVELS"
                :key="n"
                type="button"
                role="radio"
                :aria-checked="level === n"
                :class="segBtn(level === n)"
                :disabled="saving"
                :data-testid="`ma-level-${n}`"
                @click="setLevel(n)"
              >
                {{ t(`myAlgorithm.page.frequency.levels.${n}`) }}
              </button>
            </div>
          </section>

          <!-- Discovery preferences: separate switches -->
          <section :class="sectionCls" aria-labelledby="ma-discovery" data-testid="ma-discovery">
            <h2 id="ma-discovery" class="text-[15px] font-bold">{{ t("myAlgorithm.page.discovery.title") }}</h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.discovery.hint") }}</p>
            <SettingSwitch
              v-for="k in DISCOVERY_PREFS"
              :key="k"
              :model-value="discoveryOn(k)"
              :label="t(`myAlgorithm.page.discovery.names.${k}`)"
              :disabled="saving"
              :testid="`ma-discovery-${k}`"
              @update:model-value="setDiscovery(k, $event)"
            />
          </section>

          <!-- Languages -->
          <section :class="sectionCls" aria-labelledby="ma-languages" data-testid="ma-languages">
            <h2 id="ma-languages" class="flex items-center gap-2 text-[15px] font-bold"><Languages class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("myAlgorithm.page.languages.title") }}</h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.languages.hint") }}</p>
            <div class="mt-3 flex flex-wrap gap-2">
              <button
                v-for="code in CONTENT_LANGUAGES"
                :key="code"
                type="button"
                class="chip"
                :class="languages.includes(code) ? 'chip-active' : ''"
                :aria-pressed="languages.includes(code)"
                :disabled="saving"
                :data-testid="`ma-language-${code}`"
                @click="toggleLanguage(code)"
              >
                {{ t(`myAlgorithm.page.languages.names.${code}`) }}
              </button>
            </div>
          </section>

          <!-- Interests by tier -->
          <section :class="sectionCls" aria-labelledby="ma-interests" data-testid="ma-interests">
            <h2 id="ma-interests" class="flex items-center gap-2 text-[15px] font-bold"><Heart class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("myAlgorithm.page.interests.title") }}</h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.interests.hint") }}</p>
            <InterestProfile v-if="profile" :profile="profile" @changed="loadProfile" />
            <p v-else class="mt-3 text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.unavailable") }}</p>
          </section>

          <!-- Muted topics -->
          <section :class="sectionCls" aria-labelledby="ma-muted" data-testid="ma-muted">
            <h2 id="ma-muted" class="flex items-center gap-2 text-[15px] font-bold"><VolumeX class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("myAlgorithm.page.muted.title") }}</h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.muted.hint") }}</p>
            <p v-if="!muted.length" class="mt-3 text-sm text-gray-500 dark:text-gray-400" data-testid="ma-muted-empty">{{ t("myAlgorithm.page.muted.empty") }}</p>
            <ul v-else class="mt-2 divide-y divide-gray-100 dark:divide-gray-800">
              <li v-for="r in muted" :key="r.slug" class="flex items-center gap-3 py-2" data-testid="ma-muted-row">
                <bdi class="min-w-0 flex-1 truncate text-sm font-semibold" dir="auto">{{ rowLabel(r) }}</bdi>
                <button type="button" class="btn-ghost shrink-0" :disabled="busyRow === `topic:${r.slug}`" :data-testid="`ma-unmute-${r.slug}`" @click="unmute(r.slug)">{{ t("myAlgorithm.page.muted.unmute") }}</button>
              </li>
            </ul>
          </section>

          <!-- Hidden creators -->
          <section :class="sectionCls" aria-labelledby="ma-hidden" data-testid="ma-hidden">
            <h2 id="ma-hidden" class="flex items-center gap-2 text-[15px] font-bold"><UserX class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("myAlgorithm.page.hidden.title") }}</h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.hidden.hint") }}</p>
            <p v-if="!hidden.length" class="mt-3 text-sm text-gray-500 dark:text-gray-400" data-testid="ma-hidden-empty">{{ t("myAlgorithm.page.hidden.empty") }}</p>
            <ul v-else class="mt-2 divide-y divide-gray-100 dark:divide-gray-800">
              <li v-for="h in hidden" :key="h.account_id" class="flex items-center gap-3 py-2" data-testid="ma-hidden-row">
                <UserAvatar :name="directory.label(h.account_id)" :media-id="directory.avatarOf(h.account_id)" :size="36" />
                <bdi class="min-w-0 flex-1 truncate text-sm font-semibold" dir="auto">{{ directory.label(h.account_id) }}</bdi>
                <button type="button" class="btn-ghost shrink-0" :disabled="busyRow === `creator:${h.account_id}`" :data-testid="`ma-unhide-${h.account_id}`" @click="unhide(h.account_id)">{{ t("myAlgorithm.page.hidden.unhide") }}</button>
              </li>
            </ul>
          </section>

          <!-- Favourite creators (graph favorites) -->
          <section :class="sectionCls" aria-labelledby="ma-favorites" data-testid="ma-favorites">
            <h2 id="ma-favorites" class="flex items-center gap-2 text-[15px] font-bold"><Star class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("myAlgorithm.page.favorites.title") }}</h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.favorites.hint") }}</p>
            <p v-if="!favorites.length" class="mt-3 text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.favorites.empty") }}</p>
            <ul v-else class="mt-2 flex flex-wrap gap-2">
              <li v-for="id in favorites" :key="id">
                <RouterLink :to="{ name: 'profile-by-id', params: { id } }" class="chip"><bdi dir="auto">{{ directory.label(id) }}</bdi></RouterLink>
              </li>
            </ul>
            <RouterLink to="/settings/content#favorites" class="btn-ghost mt-2 inline-flex">{{ t("myAlgorithm.page.favorites.manage") }}</RouterLink>
          </section>

          <!-- Sensitive-topic inference (decision 12) and search signal (decision 7): off by default -->
          <section :class="sectionCls" aria-labelledby="ma-privacy" data-testid="ma-privacy">
            <h2 id="ma-privacy" class="flex items-center gap-2 text-[15px] font-bold"><ShieldCheck class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("myAlgorithm.page.sensitive.title") }}</h2>
            <SettingSwitch
              :model-value="prefs.sensitive_inference === true"
              :label="t('myAlgorithm.page.sensitive.label')"
              :hint="t('myAlgorithm.page.sensitive.hint')"
              :disabled="saving"
              testid="ma-sensitive"
              @update:model-value="save({ sensitive_inference: $event })"
            />
            <h3 class="mt-3 flex items-center gap-2 text-sm font-bold"><Search class="h-4 w-4" aria-hidden="true" /> {{ t("myAlgorithm.page.searchSignal.title") }}</h3>
            <SettingSwitch
              :model-value="prefs.search_signal === true"
              :label="t('myAlgorithm.page.searchSignal.label')"
              :hint="t('myAlgorithm.page.searchSignal.hint')"
              :disabled="saving"
              testid="ma-search-signal"
              @update:model-value="save({ search_signal: $event })"
            />
          </section>

          <!-- Support explain consent (decision 17) -->
          <section :class="sectionCls" aria-labelledby="ma-consent" data-testid="ma-consent">
            <h2 id="ma-consent" class="flex items-center gap-2 text-[15px] font-bold"><Clock3 class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("myAlgorithm.page.consent.title") }}</h2>
            <p class="mt-1 text-sm font-medium">{{ t("myAlgorithm.page.consent.label") }}</p>
            <p class="text-xs text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.consent.hint") }}</p>
            <p v-if="consentUntil" class="mt-2 text-sm" data-testid="ma-consent-active">{{ t("myAlgorithm.page.consent.active", { time: when(consentUntil) }) }}</p>
            <button v-if="consentUntil" type="button" class="btn-outline mt-2" :disabled="saving" data-testid="ma-consent-revoke" @click="revokeConsent">{{ t("myAlgorithm.page.consent.revoke") }}</button>
            <button v-else type="button" class="btn-soft mt-2" :disabled="saving" data-testid="ma-consent-grant" @click="grantConsent">{{ t("myAlgorithm.page.consent.grant") }}</button>
          </section>

          <!-- Reset recommendations: two steps, not undoable -->
          <section :class="sectionCls" aria-labelledby="ma-reset" data-testid="ma-reset">
            <h2 id="ma-reset" class="flex items-center gap-2 text-[15px] font-bold"><RotateCcw class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("myAlgorithm.page.reset.title") }}</h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t("myAlgorithm.page.reset.hint") }}</p>
            <p v-if="resetError" class="mt-2 text-sm text-red-600 dark:text-red-400" role="alert" data-testid="ma-reset-error">{{ resetError }}</p>
            <button type="button" class="btn-outline mt-2" :disabled="resetBusy" data-testid="ma-reset-start" @click="startReset">{{ t("myAlgorithm.page.reset.action") }}</button>
          </section>

          <!-- Turn off personalization (decisions 8 and 24) -->
          <section :class="sectionCls" aria-labelledby="ma-personalization" data-testid="ma-personalization">
            <h2 id="ma-personalization" class="flex items-center gap-2 text-[15px] font-bold"><EyeOff class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("myAlgorithm.page.personalization.title") }}</h2>
            <SettingSwitch
              :model-value="prefs.personalization_off === true"
              :label="t('myAlgorithm.page.personalization.label')"
              :hint="t('myAlgorithm.page.personalization.hint')"
              :disabled="saving"
              testid="ma-personalization-off"
              @update:model-value="save({ personalization_off: $event })"
            />
          </section>
        </template>
      </template>
    </div>

    <Teleport to="body">
      <div v-if="preview" class="fixed inset-0 z-[60] flex items-end justify-center bg-gray-950/60 backdrop-blur-sm sm:items-center sm:p-4">
        <div class="fixed inset-0" aria-hidden="true" @click="preview = null" />
        <div
          ref="dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="ma-reset-title"
          tabindex="-1"
          class="card relative z-10 w-full animate-pop-in rounded-b-none rounded-t-2xl p-5 shadow-pop sm:max-w-md sm:rounded-2xl"
          data-testid="ma-reset-dialog"
        >
          <h2 id="ma-reset-title" class="text-lg font-bold">{{ t("myAlgorithm.page.reset.dialogTitle") }}</h2>
          <h3 class="mt-3 text-sm font-bold">{{ t("myAlgorithm.page.reset.scope") }}</h3>
          <ul class="mt-1 list-disc space-y-0.5 ps-5 text-sm" data-testid="ma-reset-scope">
            <li v-for="label in uniqueLabels(preview.scope)" :key="label">{{ label }}</li>
          </ul>
          <h3 class="mt-3 text-sm font-bold">{{ t("myAlgorithm.page.reset.keeps") }}</h3>
          <ul class="mt-1 list-disc space-y-0.5 ps-5 text-sm" data-testid="ma-reset-keeps">
            <li v-for="label in uniqueLabels(preview.keeps)" :key="label">{{ label }}</li>
          </ul>
          <p class="mt-3 text-sm font-semibold text-red-600 dark:text-red-400">{{ t("myAlgorithm.page.reset.cannotUndo") }}</p>
          <div class="mt-4 flex justify-end gap-2">
            <button type="button" class="btn-ghost" data-testid="ma-reset-cancel" @click="preview = null">{{ t("myAlgorithm.page.reset.cancel") }}</button>
            <button type="button" class="btn-danger" :disabled="resetBusy" data-testid="ma-reset-confirm" @click="confirmReset">{{ t("myAlgorithm.page.reset.confirm") }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </AppShell>
</template>
