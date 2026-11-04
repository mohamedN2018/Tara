<script setup lang="ts">
import { ChevronDown, ImagePlus, X } from "lucide-vue-next";
import { computed, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { apiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { IMAGE_ACCEPT } from "@/lib/heic";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { mediaService } from "@/services/media";
import { cleanContact, invalidContactKeys, type PageContact, pageService, validatePageHandle } from "@/services/pages";

import PageContactFields from "./PageContactFields.vue";

// "Create a page": name, handle (checked like the server: 3-30 characters,
// reserved words refused), category, location, about, then optional contact
// links and photos. The photos are uploaded on submit, as the creator's own
// media; the server checks they are theirs and finished.
const emit = defineEmits<{ close: [] }>();

const { t } = useI18n();
const router = useRouter();
const dialog = ref<HTMLElement | null>(null);
useFocusTrap(dialog);
useEscapeKey(
  computed(() => true),
  () => !creating.value && emit("close"),
);

const form = ref({ name: "", handle: "", category: "", description: "", location: "" });
const contact = ref<PageContact>({});
const showContact = ref(false);
const invalidKeys = ref<string[]>([]);
const creating = ref(false);
const createError = ref("");

const handleState = computed(() => (form.value.handle.trim() ? validatePageHandle(form.value.handle) : "ok"));

type Kind = "avatar" | "cover";
const files = ref<Record<Kind, File | null>>({ avatar: null, cover: null });
const previews = ref<Record<Kind, string>>({ avatar: "", cover: "" });
function pick(kind: Kind, e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0] ?? null;
  input.value = "";
  if (!file) return;
  if (previews.value[kind]) URL.revokeObjectURL(previews.value[kind]);
  files.value[kind] = file;
  previews.value[kind] = URL.createObjectURL(file);
}
function clear(kind: Kind) {
  if (previews.value[kind]) URL.revokeObjectURL(previews.value[kind]);
  files.value[kind] = null;
  previews.value[kind] = "";
}
onBeforeUnmount(() => Object.values(previews.value).forEach((u) => u && URL.revokeObjectURL(u)));

async function create() {
  if (creating.value || handleState.value !== "ok") return;
  creating.value = true;
  createError.value = "";
  invalidKeys.value = [];
  try {
    const [avatar, cover] = await Promise.all(
      (["avatar", "cover"] as Kind[]).map((k) => (files.value[k] ? mediaService.upload(files.value[k] as File, "image") : null)),
    );
    const page = await pageService.create({
      ...form.value,
      name: form.value.name.trim(),
      handle: form.value.handle.trim(),
      contact: cleanContact(contact.value),
      ...(avatar ? { avatar_media_id: avatar.id } : {}),
      ...(cover ? { cover_media_id: cover.id } : {}),
    });
    router.push({ name: "page", params: { handle: page.handle } });
    emit("close");
  } catch (e) {
    invalidKeys.value = invalidContactKeys(apiError(e).details);
    if (invalidKeys.value.length) {
      showContact.value = true;
      createError.value = t("pageHub.edit.invalid");
    } else createError.value = errorMessage(e, { conflict: "pages.handleTaken" });
  } finally {
    creating.value = false;
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50 flex items-end justify-center bg-gray-950/60 p-0 backdrop-blur-sm sm:items-center sm:p-4">
      <div class="fixed inset-0" @click="!creating && emit('close')" />
      <div
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="page-create-title"
        tabindex="-1"
        class="card relative z-10 max-h-[92vh] w-full animate-pop-in overflow-y-auto rounded-b-none rounded-t-2xl p-4 shadow-pop sm:max-w-lg sm:rounded-2xl sm:p-5"
        data-testid="page-create-dialog"
      >
        <div class="mb-4 flex items-center justify-between">
          <h2 id="page-create-title" class="text-lg font-bold">{{ t("pageHub.create.title") }}</h2>
          <button type="button" class="icon-btn" :aria-label="t('market.close')" @click="emit('close')">
            <X class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <form class="space-y-3" @submit.prevent="create">
          <div>
            <label for="page-name" class="mb-1 block text-sm font-medium">{{ t("pages.name") }}</label>
            <input id="page-name" v-model="form.name" class="input" dir="auto" maxlength="120" required />
          </div>
          <div>
            <label for="page-handle" class="mb-1 block text-sm font-medium">{{ t("pages.handle") }}</label>
            <input
              id="page-handle"
              v-model="form.handle"
              class="input"
              dir="ltr"
              required
              maxlength="30"
              :aria-invalid="handleState !== 'ok' || undefined"
              aria-describedby="page-handle-hint"
            />
            <p
              id="page-handle-hint"
              class="mt-1 text-xs"
              :class="handleState === 'ok' ? 'text-gray-500 dark:text-gray-400' : 'text-red-600 dark:text-red-400'"
            >
              {{ handleState === "reserved" ? t("pageHub.create.handleReserved") : handleState === "invalid" ? t("pageHub.create.handleInvalid") : t("pages.handleHint") }}
            </p>
          </div>
          <div class="grid gap-3 sm:grid-cols-2">
            <div>
              <label for="page-category" class="mb-1 block text-sm font-medium">{{ t("pages.category") }}</label>
              <input id="page-category" v-model="form.category" class="input" dir="auto" maxlength="80" />
            </div>
            <div>
              <label for="page-location" class="mb-1 block text-sm font-medium">{{ t("pages.location") }}</label>
              <input id="page-location" v-model="form.location" class="input" dir="auto" maxlength="160" />
            </div>
          </div>
          <div>
            <label for="page-description" class="mb-1 block text-sm font-medium">{{ t("pages.description") }}</label>
            <textarea id="page-description" v-model="form.description" class="input min-h-20" dir="auto" rows="3" maxlength="2000" />
          </div>

          <fieldset class="rounded-xl border border-gray-200 p-3 dark:border-gray-800">
            <legend class="px-1 text-sm font-semibold">{{ t("pageHub.create.images") }}</legend>
            <div class="flex flex-wrap gap-3">
              <div v-for="k in (['avatar', 'cover'] as Kind[])" :key="k" class="flex items-center gap-2">
                <span
                  class="flex shrink-0 items-center justify-center overflow-hidden bg-gray-100 text-gray-400 dark:bg-gray-800"
                  :class="k === 'avatar' ? 'h-14 w-14 rounded-full' : 'h-14 w-24 rounded-lg'"
                >
                  <img v-if="previews[k]" :src="previews[k]" alt="" class="h-full w-full object-cover" />
                  <ImagePlus v-else class="h-5 w-5" aria-hidden="true" />
                </span>
                <span class="space-y-1">
                  <span class="block text-xs font-medium">{{ t(`pageHub.create.${k}`) }}</span>
                  <label class="btn-soft cursor-pointer px-3 py-1 text-xs">
                    {{ previews[k] ? t("pageHub.create.change") : t("pageHub.create.pick") }}
                    <input type="file" :accept="IMAGE_ACCEPT" class="sr-only" :data-testid="`page-create-${k}`" @change="pick(k, $event)" />
                  </label>
                  <button v-if="previews[k]" type="button" class="btn-ghost px-2 py-1 text-xs" @click="clear(k)">{{ t("feed.cancel") }}</button>
                </span>
              </div>
            </div>
          </fieldset>

          <div class="rounded-xl border border-gray-200 dark:border-gray-800">
            <button
              type="button"
              class="flex w-full items-center justify-between p-3 text-sm font-semibold"
              :aria-expanded="showContact"
              aria-controls="page-create-contact"
              data-testid="page-create-contact-toggle"
              @click="showContact = !showContact"
            >
              {{ t("pageHub.create.contactStep") }}
              <ChevronDown class="h-4 w-4 transition" :class="showContact ? 'rotate-180' : ''" aria-hidden="true" />
            </button>
            <div v-show="showContact" id="page-create-contact" class="border-t border-gray-200 p-3 dark:border-gray-800">
              <PageContactFields v-model="contact" id-prefix="page-create" :invalid="invalidKeys" />
            </div>
          </div>

          <p v-if="createError" class="text-sm text-red-600 dark:text-red-400" role="alert">{{ createError }}</p>
          <div class="flex justify-end gap-2">
            <button type="button" class="btn-ghost" @click="emit('close')">{{ t("feed.cancel") }}</button>
            <button type="submit" class="btn-primary" :disabled="creating || handleState !== 'ok'" data-testid="page-create-submit">
              {{ creating ? t("states.loading") : t("pages.create") }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </Teleport>
</template>
