<script setup lang="ts">
// "Login activity": the owner's own security log (GET /me/security/activity/),
// newest first. Back-to-back events of the same kind from the same region are
// grouped into one row ("Signed in ×12"), and only the first few groups show
// until "Show more", which reveals the rest and then fetches the next page.
import { AlertTriangle, LogIn, ShieldCheck } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { identityService, type SecurityActivity } from "@/services/identity";

const { t, te, locale } = useI18n();

const rows = ref<SecurityActivity[]>([]);
const next = ref<string | null>(null);
const loading = ref(true);
const failed = ref(false);
const more = ref(false);

async function load(before?: string) {
  if (before) more.value = true;
  else loading.value = true;
  failed.value = false;
  try {
    const page = await identityService.securityActivity(before);
    rows.value = before ? [...rows.value, ...page.results] : page.results;
    next.value = page.next;
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
    more.value = false;
  }
}

const COLLAPSED = 5;
const expanded = ref(false);
type Group = { id: string; type: string; region: string; latest: string; count: number };
const groups = computed<Group[]>(() => {
  const out: Group[] = [];
  for (const row of rows.value) {
    const last = out[out.length - 1];
    const region = row.ip_region || "";
    if (last && last.type === row.type && last.region === region) last.count += 1;
    else out.push({ id: row.id, type: row.type, region, latest: row.created_at, count: 1 });
  }
  return out;
});
const shown = computed(() => (expanded.value ? groups.value : groups.value.slice(0, COLLAPSED)));
const canShowMore = computed(() => (!expanded.value && groups.value.length > COLLAPSED) || !!next.value);
function showMore() {
  if (!expanded.value && groups.value.length > COLLAPSED) expanded.value = true;
  else if (next.value) void load(next.value);
}

const WARN = new Set(["login_failed", "login_blocked", "reauth_failed", "refresh_reuse_detected", "two_factor_failed"]);
const icon = (type: string) => (WARN.has(type) ? AlertTriangle : type.startsWith("login") ? LogIn : ShieldCheck);
const label = (type: string) =>
  te(`settingsCenter.activity.types.${type}`) ? t(`settingsCenter.activity.types.${type}`) : t("settingsCenter.activity.types.other");
const when = (iso: string) =>
  new Intl.DateTimeFormat(locale.value, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));

onMounted(() => load());
</script>

<template>
  <section id="activity" class="card mb-4 scroll-mt-20 p-4" data-testid="login-activity">
    <h2 class="font-semibold">{{ t("settingsCenter.activity.title") }}</h2>
    <p class="mb-3 mt-1 text-sm text-gray-600 dark:text-gray-300">{{ t("settingsCenter.activity.lead") }}</p>

    <p v-if="loading" class="text-sm text-gray-500 dark:text-gray-400">{{ t("states.loading") }}</p>
    <p v-else-if="failed && !rows.length" class="flex items-center justify-between gap-2 text-sm text-gray-500 dark:text-gray-400">
      {{ t("settingsCenter.activity.failed") }}
      <button type="button" class="btn-ghost text-sm" @click="load()">{{ t("states.retry") }}</button>
    </p>
    <p v-else-if="!rows.length" class="text-sm text-gray-500 dark:text-gray-400">{{ t("settingsCenter.activity.empty") }}</p>
    <template v-else>
      <ul class="divide-y divide-gray-100 dark:divide-gray-800">
        <li v-for="row in shown" :key="row.id" class="flex items-center gap-3 py-2 text-sm" data-testid="activity-row">
          <component
            :is="icon(row.type)"
            class="h-5 w-5 shrink-0"
            :class="WARN.has(row.type) ? 'text-amber-600 dark:text-amber-400' : 'text-gray-500 dark:text-gray-400'"
            aria-hidden="true"
          />
          <span class="min-w-0 flex-1">
            <span class="block font-medium">
              {{ label(row.type) }}
              <span v-if="row.count > 1" class="ms-1 text-xs font-normal text-gray-500 dark:text-gray-400" data-testid="activity-count">
                {{ t("settingsCenter.activity.times", { n: row.count }) }}
              </span>
            </span>
            <span class="block text-xs text-gray-500 dark:text-gray-400">
              <template v-if="row.region">{{ row.region }} · </template>{{ row.count > 1 ? t("settingsCenter.activity.latest", { date: when(row.latest) }) : when(row.latest) }}
            </span>
          </span>
        </li>
      </ul>
      <button v-if="canShowMore" type="button" class="btn-ghost mt-2 w-full text-sm" :disabled="more" data-testid="activity-more" @click="showMore">
        {{ t("settingsCenter.activity.more") }}
      </button>
    </template>
  </section>
</template>
