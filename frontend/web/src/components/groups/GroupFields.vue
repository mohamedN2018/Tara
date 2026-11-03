<script setup lang="ts">
import { EyeOff, Globe2, ImagePlus, Lock, Trash2 } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import { useMediaUrl } from "@/lib/useMediaUrl";
import {
  GROUP_CATEGORIES,
  GROUP_PRIVACIES,
  type GroupFormValue,
  MAX_DESCRIPTION,
  MAX_NAME,
} from "@/services/groups";
import { mediaService } from "@/services/media";
import { useToastStore } from "@/stores/toasts";

// The fields the creation form and the settings section share.
const model = defineModel<GroupFormValue>({ required: true });
const props = withDefaults(defineProps<{ idPrefix?: string; canChangePrivacy?: boolean }>(), {
  idPrefix: "group",
  canChangePrivacy: true,
});
const emit = defineEmits<{ uploading: [busy: boolean] }>();

const { t } = useI18n();
const toasts = useToastStore();
const uploading = ref(false);
const coverUrl = useMediaUrl(() => model.value.cover_media_id);
const ICONS = { public: Globe2, private: Lock, hidden: EyeOff } as const;
const id = (name: string) => `${props.idPrefix}-${name}`;

async function onCover(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  uploading.value = true;
  emit("uploading", true);
  try {
    model.value.cover_media_id = (await mediaService.upload(file, "image")).id;
  } catch (err) {
    toasts.error(err, { request_failed: "errors.uploadFailed" });
  } finally {
    uploading.value = false;
    emit("uploading", false);
  }
}
</script>

<template>
  <div class="space-y-4">
    <div>
      <p class="label">{{ t("groups.form.cover") }}</p>
      <div class="relative h-36 overflow-hidden rounded-2xl bg-tara-gradient">
        <img v-if="coverUrl" :src="coverUrl" alt="" class="h-full w-full object-cover" />
        <div class="absolute inset-0 flex items-end justify-end gap-2 p-3">
          <label class="btn-soft cursor-pointer bg-white/90 dark:bg-gray-900/90" :class="uploading ? 'pointer-events-none opacity-60' : ''">
            <ImagePlus class="h-4 w-4" aria-hidden="true" />
            {{ uploading ? t("groups.form.uploading") : model.cover_media_id ? t("groups.form.changeCover") : t("groups.form.addCover") }}
            <input type="file" accept="image/*" class="sr-only" :disabled="uploading" @change="onCover" />
          </label>
          <button
            v-if="model.cover_media_id"
            type="button"
            class="btn-soft bg-white/90 dark:bg-gray-900/90"
            :aria-label="t('groups.form.removeCover')"
            @click="model.cover_media_id = null"
          >
            <Trash2 class="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>

    <div>
      <label :for="id('name')" class="label">{{ t("groups.form.name") }}</label>
      <input :id="id('name')" v-model="model.name" class="input" :maxlength="MAX_NAME" required dir="auto" />
    </div>

    <div>
      <label :for="id('description')" class="label">{{ t("groups.form.description") }}</label>
      <textarea :id="id('description')" v-model="model.description" class="input min-h-24" rows="3" :maxlength="MAX_DESCRIPTION" dir="auto" />
      <p class="mt-1 text-end text-xs tabular-nums text-gray-500 dark:text-gray-400">{{ model.description.length }} / {{ MAX_DESCRIPTION }}</p>
    </div>

    <div>
      <label :for="id('category')" class="label">{{ t("groups.form.category") }}</label>
      <select :id="id('category')" v-model="model.category" class="input">
        <option v-for="c in GROUP_CATEGORIES" :key="c" :value="c">{{ t(`groups.categories.${c}`) }}</option>
      </select>
    </div>

    <fieldset :disabled="!canChangePrivacy">
      <legend class="label">{{ t("groups.form.privacy") }}</legend>
      <div class="mt-1 grid gap-2 sm:grid-cols-3">
        <label
          v-for="p in GROUP_PRIVACIES"
          :key="p"
          class="flex cursor-pointer items-start gap-2 rounded-xl border p-3 text-sm transition"
          :class="model.privacy === p ? 'border-brand-500 bg-brand-50 dark:border-brand-400 dark:bg-brand-950/40' : 'border-gray-200 dark:border-gray-800'"
        >
          <input v-model="model.privacy" type="radio" :name="id('privacy')" :value="p" class="mt-0.5 accent-brand-600" />
          <span>
            <span class="flex items-center gap-1 font-semibold">
              <component :is="ICONS[p]" class="h-4 w-4" aria-hidden="true" /> {{ t(`groups.privacy.${p}`) }}
            </span>
            <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t(`groups.privacyHints.${p}`) }}</span>
          </span>
        </label>
      </div>
    </fieldset>

    <div class="space-y-2">
      <label class="flex cursor-pointer items-start gap-3 rounded-xl border border-gray-200 p-3 text-sm dark:border-gray-800">
        <input v-model="model.membership_approval" type="checkbox" class="mt-0.5 accent-brand-600" />
        <span>
          <span class="block font-semibold">{{ t("groups.form.membershipApproval") }}</span>
          <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t("groups.form.membershipApprovalHint") }}</span>
        </span>
      </label>
      <label class="flex cursor-pointer items-start gap-3 rounded-xl border border-gray-200 p-3 text-sm dark:border-gray-800">
        <input v-model="model.post_approval" type="checkbox" class="mt-0.5 accent-brand-600" />
        <span>
          <span class="block font-semibold">{{ t("groups.form.postApproval") }}</span>
          <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t("groups.form.postApprovalHint") }}</span>
        </span>
      </label>
    </div>
  </div>
</template>
