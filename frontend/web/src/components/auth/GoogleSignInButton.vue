<script setup lang="ts">
// Renders Google's own button when the server has Google sign-in enabled, and
// nothing at all otherwise (the GIS script is not even requested).
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { renderGoogleButton, type GoogleButtonText } from "@/lib/googleIdentity";
import { identityService } from "@/services/identity";
import { useUiStore } from "@/stores/ui";

const props = withDefaults(defineProps<{ text?: GoogleButtonText; divider?: boolean }>(), {
  text: "continue_with",
  divider: false,
});
const emit = defineEmits<{ credential: [credential: string]; available: [enabled: boolean] }>();

const { t, locale } = useI18n();
const ui = useUiStore();
const host = ref<HTMLElement | null>(null);
const clientId = ref("");
const failed = ref(false);
const dark = computed(
  () =>
    ui.theme === "dark" ||
    (ui.theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches),
);

async function render() {
  if (!host.value || !clientId.value) return;
  failed.value = false;
  try {
    await renderGoogleButton(host.value, {
      clientId: clientId.value,
      locale: locale.value,
      text: props.text,
      dark: dark.value,
      width: Math.min(host.value.clientWidth || 320, 400),
      onCredential: (credential) => emit("credential", credential),
    });
  } catch {
    failed.value = true;
  }
}

onMounted(async () => {
  const providers = await identityService.providers();
  emit("available", providers.google.enabled);
  if (!providers.google.enabled) return;
  clientId.value = providers.google.client_id;
  await nextTick(); // the host element renders once clientId is set
  void render();
});

// Google renders the button text itself, so re-render on language/theme change.
watch([locale, dark], () => void render());
</script>

<template>
  <div v-if="clientId">
    <div v-if="divider" class="my-4 flex items-center gap-3 text-xs text-gray-400 dark:text-gray-500">
      <span class="h-px flex-1 bg-gray-200 dark:bg-gray-800" />
      {{ t("accountSecurity.google.or") }}
      <span class="h-px flex-1 bg-gray-200 dark:bg-gray-800" />
    </div>
    <!-- Google's iframe sets its own direction; keep the slot centred in RTL too. -->
    <div ref="host" class="flex min-h-[44px] w-full justify-center" />
    <p v-if="failed" class="mt-2 text-center text-xs text-gray-500 dark:text-gray-400" role="status">
      {{ t("accountSecurity.google.unavailable") }}
      <button type="button" class="font-semibold underline" @click="render">{{ t("states.retry") }}</button>
    </p>
  </div>
</template>
