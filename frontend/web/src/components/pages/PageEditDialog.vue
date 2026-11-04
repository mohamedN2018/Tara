<script setup lang="ts">
import { X } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { apiError } from "@/lib/api";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { canManagePage, cleanContact, invalidContactKeys, type Page, type PageContact, pageService } from "@/services/pages";
import { useToastStore } from "@/stores/toasts";

import PageContactFields from "./PageContactFields.vue";

// "Edit page" (editors and up): details and contact info. Owners and admins
// may also publish or hide the page; `suspended` belongs to moderation.
const props = defineProps<{ page: Page }>();
const emit = defineEmits<{ close: []; saved: [page: Page] }>();

const { t } = useI18n();
const toasts = useToastStore();
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
const saving = ref(false);
useEscapeKey(
  computed(() => true),
  () => !saving.value && emit("close"),
);
const form = ref({
  name: props.page.name,
  category: props.page.category,
  location: props.page.location,
  description: props.page.description,
  status: props.page.status,
});
const contact = ref<PageContact>({ ...(props.page.contact ?? {}) });
const invalidKeys = ref<string[]>([]);
const error = ref("");
const manage = computed(() => canManagePage(props.page) && props.page.status !== "suspended");

async function save() {
  if (saving.value) return;
  saving.value = true;
  error.value = "";
  invalidKeys.value = [];
  const { status, ...details } = form.value;
  try {
    const page = await pageService.update(props.page.id, {
      ...details,
      name: details.name.trim(),
      contact: cleanContact(contact.value),
      ...(manage.value ? { status } : {}),
    });
    toasts.success(t("pageHub.edit.saved"));
    emit("saved", page);
    emit("close");
  } catch (e) {
    invalidKeys.value = invalidContactKeys(apiError(e).details);
    if (invalidKeys.value.length) error.value = t("pageHub.edit.invalid");
    else toasts.error(e);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 backdrop-blur-sm sm:items-center sm:p-4">
      <div class="fixed inset-0" @click="!saving && emit('close')" />
      <form
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="page-edit-title"
        tabindex="-1"
        class="card relative z-10 max-h-[92vh] w-full animate-pop-in space-y-3 overflow-y-auto rounded-b-none rounded-t-2xl p-4 shadow-pop sm:max-w-xl sm:rounded-2xl sm:p-5"
        data-testid="page-edit-dialog"
        @submit.prevent="save"
      >
        <div class="flex items-center justify-between">
          <h2 id="page-edit-title" class="text-lg font-bold">{{ t("pageHub.edit.title") }}</h2>
          <button type="button" class="icon-btn" :aria-label="t('market.close')" @click="emit('close')">
            <X class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <div>
          <label for="page-edit-name" class="mb-1 block text-sm font-medium">{{ t("pages.name") }}</label>
          <input id="page-edit-name" v-model="form.name" class="input" dir="auto" maxlength="120" required />
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <div>
            <label for="page-edit-category" class="mb-1 block text-sm font-medium">{{ t("pages.category") }}</label>
            <input id="page-edit-category" v-model="form.category" class="input" dir="auto" maxlength="80" />
          </div>
          <div>
            <label for="page-edit-location" class="mb-1 block text-sm font-medium">{{ t("pages.location") }}</label>
            <input id="page-edit-location" v-model="form.location" class="input" dir="auto" maxlength="160" />
          </div>
        </div>
        <div>
          <label for="page-edit-description" class="mb-1 block text-sm font-medium">{{ t("pages.description") }}</label>
          <textarea id="page-edit-description" v-model="form.description" class="input min-h-20" dir="auto" rows="3" maxlength="2000" />
        </div>
        <div v-if="manage">
          <label for="page-edit-status" class="mb-1 block text-sm font-medium">{{ t("pages.statusLabel") }}</label>
          <select id="page-edit-status" v-model="form.status" class="input">
            <option value="published">{{ t("pages.status.published") }}</option>
            <option value="draft">{{ t("pages.status.draft") }}</option>
          </select>
        </div>
        <fieldset class="space-y-2">
          <legend class="text-sm font-semibold">{{ t("pageHub.edit.contact") }}</legend>
          <PageContactFields v-model="contact" id-prefix="page-edit" :invalid="invalidKeys" />
        </fieldset>
        <p v-if="error" class="text-sm text-red-600 dark:text-red-400" role="alert">{{ error }}</p>
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="emit('close')">{{ t("feed.cancel") }}</button>
          <button type="submit" class="btn-primary" :disabled="saving" data-testid="page-edit-save">{{ t("settings.save") }}</button>
        </div>
      </form>
    </div>
  </Teleport>
</template>
