<script setup lang="ts">
import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import {
  type Group,
  GROUP_ERRORS,
  type GroupRule,
  groupsService,
  MAX_RULE_BODY,
  MAX_RULE_TITLE,
  MAX_RULES,
} from "@/services/groups";
import { useToastStore } from "@/stores/toasts";

// Add, edit, delete and reorder the group's rules (admins and owners).
const props = defineProps<{ group: Group }>();

const { t } = useI18n();
const toasts = useToastStore();
const rules = ref<GroupRule[]>([]);
const loading = ref(true);
const error = ref(false);
const busy = ref(false);
const editingId = ref<string | "new" | null>(null);
const draftTitle = ref("");
const draftBody = ref("");
const groupRef = () => props.group.handle || props.group.id;

async function load() {
  loading.value = true;
  error.value = false;
  try {
    rules.value = await groupsService.rules(groupRef());
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

function startEdit(rule: GroupRule | null) {
  editingId.value = rule ? rule.id : "new";
  draftTitle.value = rule?.title ?? "";
  draftBody.value = rule?.body ?? "";
}

async function guarded(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  try {
    await action();
  } catch (e) {
    toasts.error(e, GROUP_ERRORS);
  } finally {
    busy.value = false;
  }
}

const save = () =>
  guarded(async () => {
    const title = draftTitle.value.trim();
    if (!title) return;
    const body = draftBody.value.trim();
    if (editingId.value === "new") {
      rules.value = [...rules.value, await groupsService.addRule(groupRef(), { title, body })];
    } else if (editingId.value) {
      const saved = await groupsService.updateRule(groupRef(), editingId.value, { title, body });
      rules.value = rules.value.map((r) => (r.id === saved.id ? saved : r));
    }
    editingId.value = null;
    toasts.success(t("groups.rules.saved"));
  });

const remove = (rule: GroupRule) =>
  guarded(async () => {
    if (!window.confirm(t("groups.rules.deleteConfirm", { title: rule.title }))) return;
    await groupsService.deleteRule(groupRef(), rule.id);
    rules.value = rules.value.filter((r) => r.id !== rule.id);
  });

const move = (index: number, step: -1 | 1) =>
  guarded(async () => {
    const next = [...rules.value];
    const target = index + step;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    rules.value = await groupsService.reorderRules(
      groupRef(),
      next.map((r) => r.id),
    );
  });

onMounted(load);
</script>

<template>
  <div class="space-y-3">
    <LoadingSkeleton v-if="loading" :rows="2" />
    <ErrorState v-else-if="error" @retry="load" />
    <template v-else>
      <ol class="space-y-2">
        <li v-for="(rule, i) in rules" :key="rule.id" class="rounded-xl border border-gray-200 p-3 dark:border-gray-800">
          <form v-if="editingId === rule.id" class="space-y-2" @submit.prevent="save">
            <input v-model="draftTitle" class="input" :maxlength="MAX_RULE_TITLE" :aria-label="t('groups.rules.ruleTitle')" dir="auto" required />
            <textarea v-model="draftBody" class="input min-h-16" rows="2" :maxlength="MAX_RULE_BODY" :aria-label="t('groups.rules.ruleBody')" dir="auto" />
            <div class="flex justify-end gap-2">
              <button type="button" class="btn-ghost" @click="editingId = null">{{ t("feed.cancel") }}</button>
              <button type="submit" class="btn-primary" :disabled="busy || !draftTitle.trim()">{{ t("groups.rules.save") }}</button>
            </div>
          </form>
          <div v-else class="flex items-start gap-2">
            <span class="mt-0.5 text-sm font-bold text-brand-600 dark:text-brand-300">{{ i + 1 }}</span>
            <div class="min-w-0 flex-1">
              <p class="font-semibold" dir="auto">{{ rule.title }}</p>
              <p v-if="rule.body" class="whitespace-pre-line text-sm text-gray-600 dark:text-gray-300" dir="auto">{{ rule.body }}</p>
            </div>
            <div class="flex shrink-0 gap-1">
              <button type="button" class="icon-btn h-8 w-8" :disabled="busy || i === 0" :aria-label="t('groups.rules.moveUp', { n: i + 1 })" @click="move(i, -1)">
                <ArrowUp class="h-4 w-4" aria-hidden="true" />
              </button>
              <button type="button" class="icon-btn h-8 w-8" :disabled="busy || i === rules.length - 1" :aria-label="t('groups.rules.moveDown', { n: i + 1 })" @click="move(i, 1)">
                <ArrowDown class="h-4 w-4" aria-hidden="true" />
              </button>
              <button type="button" class="icon-btn h-8 w-8" :aria-label="t('groups.rules.edit', { n: i + 1 })" @click="startEdit(rule)">
                <Pencil class="h-4 w-4" aria-hidden="true" />
              </button>
              <button type="button" class="icon-btn h-8 w-8" :disabled="busy" :aria-label="t('groups.rules.deleteN', { n: i + 1 })" @click="remove(rule)">
                <Trash2 class="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          </div>
        </li>
      </ol>
      <p v-if="!rules.length && editingId !== 'new'" class="text-sm text-gray-500 dark:text-gray-400">{{ t("groups.rules.none") }}</p>

      <form v-if="editingId === 'new'" class="space-y-2 rounded-xl border border-brand-200 p-3 dark:border-brand-900" @submit.prevent="save">
        <input v-model="draftTitle" class="input" :maxlength="MAX_RULE_TITLE" :placeholder="t('groups.rules.ruleTitle')" :aria-label="t('groups.rules.ruleTitle')" dir="auto" required />
        <textarea v-model="draftBody" class="input min-h-16" rows="2" :maxlength="MAX_RULE_BODY" :placeholder="t('groups.rules.ruleBody')" :aria-label="t('groups.rules.ruleBody')" dir="auto" />
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="editingId = null">{{ t("feed.cancel") }}</button>
          <button type="submit" class="btn-primary" :disabled="busy || !draftTitle.trim()">{{ t("groups.rules.save") }}</button>
        </div>
      </form>
      <button v-else type="button" class="btn-soft" :disabled="rules.length >= MAX_RULES" @click="startEdit(null)">
        <Plus class="h-4 w-4" aria-hidden="true" /> {{ t("groups.rules.add") }}
      </button>
      <p v-if="rules.length >= MAX_RULES" class="text-xs text-gray-500 dark:text-gray-400">{{ t("groups.rules.max", { max: MAX_RULES }) }}</p>
    </template>
  </div>
</template>
