<script setup lang="ts">
import { KeyRound, RotateCcw, X } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { matrixDiff, namespaceOf, toggleCapability, withImplied, type MatrixChange } from "@/lib/capabilities";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { adminService, type CapabilityMatrix } from "@/services/admin";
import { useToastStore } from "@/stores/toasts";

import { useAdminLabels } from "./labels";

const { t } = useI18n();
const toasts = useToastStore();
const { capLabel, namespaceLabel, roleLabel } = useAdminLabels();

const matrix = ref<CapabilityMatrix | null>(null);
const loading = ref(true);
const error = ref(false);
const saving = ref(false);
const status = ref("");
// role -> effective keys: as last saved, and as edited on screen.
const saved = ref<Record<string, Set<string>>>({});
const edited = ref<Record<string, Set<string>>>({});

const previewOpen = ref(false);
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
useEscapeKey(previewOpen, () => (previewOpen.value = false));

function apply(next: CapabilityMatrix) {
  matrix.value = next;
  const fromServer = (role: string) => new Set(next.effective[role] ?? []);
  saved.value = Object.fromEntries(next.roles.map((r) => [r, fromServer(r)]));
  edited.value = Object.fromEntries(next.roles.map((r) => [r, fromServer(r)]));
}

async function load() {
  loading.value = true;
  error.value = false;
  try {
    apply(await adminService.capabilityMatrix());
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

const isLocked = (role: string) => matrix.value?.locked_roles.includes(role) ?? false;

const defaults = computed<Record<string, Set<string>>>(() =>
  Object.fromEntries((matrix.value?.roles ?? []).map((r) => [r, withImplied(matrix.value?.defaults[r] ?? [])])),
);

/** Capabilities grouped by namespace, in the server's order. */
const groups = computed(() => {
  const byNs = new Map<string, string[]>();
  for (const cap of matrix.value?.capabilities ?? []) {
    const ns = cap.namespace || namespaceOf(cap.key);
    byNs.set(ns, [...(byNs.get(ns) ?? []), cap.key]);
  }
  return [...byNs.entries()].map(([ns, keys]) => ({ ns, keys }));
});

const has = (role: string, key: string) => isLocked(role) || (edited.value[role]?.has(key) ?? false);
const isCustom = (role: string, key: string) => !isLocked(role) && has(role, key) !== (defaults.value[role]?.has(key) ?? false);

function toggle(role: string, key: string, on: boolean) {
  if (isLocked(role)) return;
  edited.value = { ...edited.value, [role]: toggleCapability(edited.value[role] ?? [], key, on) };
  status.value = "";
}

function resetCell(role: string, key: string) {
  toggle(role, key, defaults.value[role]?.has(key) ?? false);
}

const changes = computed<MatrixChange[]>(() => matrixDiff(saved.value, edited.value, matrix.value?.defaults ?? {}));

function discard() {
  if (matrix.value) apply(matrix.value);
}

async function save() {
  if (saving.value || !changes.value.length) return;
  saving.value = true;
  try {
    apply(await adminService.saveCapabilities(changes.value));
    previewOpen.value = false;
    status.value = t("admin.matrix.saved");
    toasts.success(t("admin.matrix.saved"));
  } catch (e) {
    toasts.error(e); // Nothing was saved: the edits stay on screen.
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section aria-labelledby="matrix-title">
    <h2 id="matrix-title" class="mb-1 flex items-center gap-2 font-semibold">
      <KeyRound class="h-5 w-5 text-brand-600 dark:text-brand-300" aria-hidden="true" /> {{ t("admin.matrix.title") }}
    </h2>
    <p class="mb-3 text-xs text-gray-500 dark:text-gray-400">{{ t("admin.matrix.hint") }}</p>

    <LoadingSkeleton v-if="loading" :rows="3" />
    <ErrorState v-else-if="error || !matrix" @retry="load" />
    <template v-else>
      <div class="card overflow-x-auto">
        <table class="w-full border-collapse text-sm" data-testid="capability-matrix">
          <thead>
            <tr>
              <th scope="col" class="px-3 py-2 text-start font-semibold">{{ t("admin.matrix.capability") }}</th>
              <th v-for="role in matrix.roles" :key="role" scope="col" class="px-3 py-2 text-center font-semibold">
                {{ roleLabel(role) }}
              </th>
            </tr>
          </thead>
          <tbody v-for="group in groups" :key="group.ns">
            <tr class="bg-gray-50 dark:bg-gray-900/60">
              <th :colspan="matrix.roles.length + 1" scope="colgroup" class="px-3 py-1.5 text-start text-xs font-bold uppercase tracking-wide text-brand-700 dark:text-brand-300">
                {{ namespaceLabel(group.ns) }}
              </th>
            </tr>
            <tr v-for="key in group.keys" :key="key" class="border-t border-gray-100 dark:border-gray-800">
              <th scope="row" class="px-3 py-2 text-start font-normal">
                <span class="block">{{ capLabel(key) }}</span>
                <span class="block text-xs text-gray-500 dark:text-gray-400" dir="ltr">{{ key }}</span>
              </th>
              <td v-for="role in matrix.roles" :key="role" class="px-3 py-2 text-center">
                <span class="inline-flex items-center gap-1">
                  <input
                    type="checkbox"
                    class="h-4 w-4 accent-brand-600"
                    :checked="has(role, key)"
                    :disabled="isLocked(role) || saving"
                    :title="isLocked(role) ? t('admin.matrix.locked') : undefined"
                    :aria-label="t('admin.matrix.cell', { capability: capLabel(key), role: roleLabel(role) })"
                    :data-cell="`${role}|${key}`"
                    @change="toggle(role, key, ($event.target as HTMLInputElement).checked)"
                  />
                  <template v-if="isCustom(role, key)">
                    <span class="h-1.5 w-1.5 rounded-full bg-accent-500" role="img" :aria-label="t('admin.matrix.custom')" :title="t('admin.matrix.custom')" />
                    <button
                      type="button"
                      class="rounded p-0.5 text-gray-500 hover:text-brand-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500 dark:text-gray-400"
                      :aria-label="t('admin.matrix.reset', { capability: capLabel(key), role: roleLabel(role) })"
                      :title="t('admin.matrix.reset', { capability: capLabel(key), role: roleLabel(role) })"
                      @click="resetCell(role, key)"
                    >
                      <RotateCcw class="h-3.5 w-3.5" aria-hidden="true" />
                    </button>
                  </template>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="mt-3 flex flex-wrap items-center gap-2">
        <span class="text-sm text-gray-600 dark:text-gray-300">{{ t("admin.matrix.pending", changes.length) }}</span>
        <span class="ms-auto flex gap-2">
          <button type="button" class="btn-ghost text-sm" :disabled="!changes.length || saving" @click="discard">{{ t("admin.matrix.discard") }}</button>
          <button type="button" class="btn-primary text-sm" :disabled="!changes.length || saving" @click="previewOpen = true">
            {{ t("admin.matrix.review") }}
          </button>
        </span>
      </div>
      <p class="sr-only" role="status" aria-live="polite">{{ status }}</p>
    </template>

    <div v-if="previewOpen" class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 p-0 backdrop-blur-sm sm:items-center sm:p-4">
      <div class="fixed inset-0" @click="previewOpen = false" />
      <div
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="matrix-preview-title"
        tabindex="-1"
        class="card relative z-10 max-h-[92vh] w-full animate-pop-in overflow-y-auto rounded-b-none rounded-t-2xl p-4 shadow-pop sm:max-w-lg sm:rounded-2xl sm:p-5"
      >
        <div class="mb-2 flex items-center justify-between">
          <h2 id="matrix-preview-title" class="text-lg font-bold">{{ t("admin.matrix.previewTitle") }}</h2>
          <button type="button" class="rounded-full p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800" :aria-label="t('admin.matrix.cancel')" @click="previewOpen = false">
            <X class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <p class="mb-3 text-sm text-gray-500 dark:text-gray-400">{{ t("admin.matrix.previewHint") }}</p>
        <ul class="space-y-1.5" data-testid="matrix-diff">
          <li v-for="c in changes" :key="`${c.role}|${c.capability}`" class="flex items-center gap-2 text-sm">
            <span
              class="shrink-0 rounded-full px-2 py-0.5 text-xs font-medium"
              :class="
                c.state === 'grant'
                  ? 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300'
                  : c.state === 'revoke'
                    ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300'
                    : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
              "
            >
              {{ t(`admin.matrix.states.${c.state}`) }}
            </span>
            <span>{{ t("admin.matrix.cell", { capability: capLabel(c.capability), role: roleLabel(c.role) }) }}</span>
          </li>
        </ul>
        <div class="mt-4 flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="previewOpen = false">{{ t("admin.matrix.cancel") }}</button>
          <button type="button" class="btn-primary" :disabled="saving" @click="save">{{ t("admin.matrix.save") }}</button>
        </div>
      </div>
    </div>
  </section>
</template>
