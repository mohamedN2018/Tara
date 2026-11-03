<script setup lang="ts">
import { ArrowLeft, Check, Plus, Trash2, X } from "lucide-vue-next";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import GroupFields from "@/components/groups/GroupFields.vue";
import AppShell from "@/components/layout/AppShell.vue";
import { httpStatus } from "@/lib/api";
import { mediaErrorKey } from "@/lib/errors";
import {
  GROUP_ERRORS,
  type GroupFormValue,
  groupPath,
  groupsService,
  HANDLE_MAX,
  MAX_RULE_BODY,
  MAX_RULE_TITLE,
  MAX_RULES,
  suggestHandle,
  validateHandle,
} from "@/services/groups";
import { useToastStore } from "@/stores/toasts";

// Any signed-in account can create a group; the creator becomes its owner.
const { t } = useI18n();
const router = useRouter();
const toasts = useToastStore();

const value = reactive<GroupFormValue>({
  name: "",
  description: "",
  category: "general",
  privacy: "public",
  membership_approval: false,
  post_approval: false,
  cover_media_id: null,
});
const handle = ref("");
const handleTouched = ref(false);
const availability = ref<"idle" | "checking" | "available" | "taken">("idle");
const rules = ref<{ title: string; body: string }[]>([]);
const uploading = ref(false);
const saving = ref(false);
const formError = ref("");

const problem = computed(() => (handle.value ? validateHandle(handle.value) : null));

// Suggest the handle from the name until the person types one.
watch(
  () => value.name,
  (name) => {
    if (!handleTouched.value) handle.value = suggestHandle(name);
  },
);

let checkTimer: number | undefined;
let checkGeneration = 0;
watch(handle, (h) => {
  window.clearTimeout(checkTimer);
  availability.value = "idle";
  if (!h || validateHandle(h)) return;
  availability.value = "checking";
  const mine = ++checkGeneration;
  checkTimer = window.setTimeout(async () => {
    try {
      await groupsService.get(h);
      if (mine === checkGeneration) availability.value = "taken";
    } catch (e) {
      // 404: free as far as this viewer can tell; the server has the last word (409).
      if (mine === checkGeneration) availability.value = httpStatus(e) === 404 ? "available" : "idle";
    }
  }, 400);
});

function onHandleInput(e: Event) {
  handleTouched.value = true;
  handle.value = (e.target as HTMLInputElement).value.toLowerCase().trim();
}

function addRule() {
  if (rules.value.length < MAX_RULES) rules.value.push({ title: "", body: "" });
}

async function submit() {
  formError.value = "";
  if (!value.name.trim()) {
    formError.value = t("groups.form.nameRequired");
    return;
  }
  if (!handle.value || problem.value) {
    formError.value = t(`groups.handle.${problem.value ?? "too_short"}`, { min: 3, max: HANDLE_MAX });
    return;
  }
  saving.value = true;
  try {
    const group = await groupsService.create({
      ...value,
      name: value.name.trim(),
      handle: handle.value,
      rules: rules.value.map((r) => ({ title: r.title.trim(), body: r.body.trim() })).filter((r) => r.title),
    });
    toasts.success(t("groups.form.created"));
    router.push(groupPath(group));
  } catch (e) {
    const media = mediaErrorKey(e);
    if (media) toasts.push({ text: t(media), icon: "error" });
    else toasts.error(e, GROUP_ERRORS);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <AppShell :right="false">
    <div class="mx-auto w-full max-w-[720px] space-y-4">
      <button class="btn-ghost" @click="router.back()">
        <ArrowLeft class="h-4 w-4 rtl:rotate-180" aria-hidden="true" /> {{ t("states.back") }}
      </button>
      <form class="card space-y-4 p-4 sm:p-6" novalidate @submit.prevent="submit">
        <h1 class="text-xl font-bold">{{ t("groups.form.title") }}</h1>

        <GroupFields v-model="value" id-prefix="group-new" @uploading="uploading = $event" />

        <div>
          <label for="group-new-handle" class="label">{{ t("groups.form.handle") }}</label>
          <div class="flex items-center gap-1 rounded-xl" dir="ltr">
            <span class="text-sm text-gray-500 dark:text-gray-400">/groups/</span>
            <input
              id="group-new-handle"
              :value="handle"
              class="input"
              :maxlength="HANDLE_MAX"
              autocomplete="off"
              spellcheck="false"
              :aria-invalid="!!problem || availability === 'taken'"
              aria-describedby="group-new-handle-status"
              @input="onHandleInput"
            />
          </div>
          <p id="group-new-handle-status" class="mt-1 flex items-center gap-1 text-xs" aria-live="polite">
            <template v-if="problem">
              <X class="h-3.5 w-3.5 text-red-600" aria-hidden="true" />
              <span class="text-red-600 dark:text-red-400">{{ t(`groups.handle.${problem}`, { min: 3, max: HANDLE_MAX }) }}</span>
            </template>
            <template v-else-if="availability === 'taken'">
              <X class="h-3.5 w-3.5 text-red-600" aria-hidden="true" />
              <span class="text-red-600 dark:text-red-400">{{ t("groups.handle.taken") }}</span>
            </template>
            <template v-else-if="availability === 'available'">
              <Check class="h-3.5 w-3.5 text-brand-600" aria-hidden="true" />
              <span class="text-brand-700 dark:text-brand-300">{{ t("groups.handle.available") }}</span>
            </template>
            <span v-else-if="availability === 'checking'" class="text-gray-500 dark:text-gray-400">{{ t("groups.handle.checking") }}</span>
            <span v-else class="text-gray-500 dark:text-gray-400">{{ t("groups.handle.hint") }}</span>
          </p>
        </div>

        <section aria-labelledby="group-new-rules">
          <div class="mb-2 flex items-center justify-between">
            <h2 id="group-new-rules" class="label mb-0">{{ t("groups.rules.title") }}</h2>
            <button type="button" class="btn-ghost text-sm" :disabled="rules.length >= MAX_RULES" @click="addRule">
              <Plus class="h-4 w-4" aria-hidden="true" /> {{ t("groups.rules.add") }}
            </button>
          </div>
          <ol class="space-y-2">
            <li v-for="(rule, i) in rules" :key="i" class="space-y-2 rounded-xl border border-gray-200 p-3 dark:border-gray-800">
              <div class="flex items-center gap-2">
                <span class="text-sm font-bold text-brand-600 dark:text-brand-300">{{ i + 1 }}</span>
                <input
                  v-model="rule.title"
                  class="input"
                  :maxlength="MAX_RULE_TITLE"
                  :placeholder="t('groups.rules.ruleTitle')"
                  :aria-label="t('groups.rules.ruleTitleN', { n: i + 1 })"
                  dir="auto"
                />
                <button type="button" class="icon-btn shrink-0" :aria-label="t('groups.rules.delete')" @click="rules.splice(i, 1)">
                  <Trash2 class="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
              <textarea
                v-model="rule.body"
                class="input min-h-16"
                rows="2"
                :maxlength="MAX_RULE_BODY"
                :placeholder="t('groups.rules.ruleBody')"
                :aria-label="t('groups.rules.ruleBodyN', { n: i + 1 })"
                dir="auto"
              />
            </li>
          </ol>
          <p v-if="!rules.length" class="text-xs text-gray-500 dark:text-gray-400">{{ t("groups.rules.emptyHint") }}</p>
        </section>

        <p v-if="formError" class="text-sm text-red-600 dark:text-red-400" role="alert">{{ formError }}</p>
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="router.back()">{{ t("feed.cancel") }}</button>
          <button type="submit" class="btn-gradient" :disabled="saving || uploading">
            {{ saving ? t("groups.form.creating") : t("groups.form.submit") }}
          </button>
        </div>
      </form>
    </div>
  </AppShell>
</template>
