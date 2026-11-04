<script setup lang="ts">
// A boolean account preference saved with PATCH /me/ (identity enforces it):
// "Show when you're active" (show_presence) and login alerts.
import { computed, ref } from "vue";

import { refreshSession } from "@/lib/api";
import { tokenStore } from "@/lib/tokens";
import { realtime } from "@/lib/ws";
import { identityService } from "@/services/identity";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";

import SettingSwitch from "./SettingSwitch.vue";

const props = defineProps<{ field: "show_presence" | "login_alerts"; label: string; hint?: string; savedText: string }>();

const auth = useAuthStore();
const toasts = useToastStore();
const saving = ref(false);
const value = computed(() => auth.account?.[props.field] !== false);

async function change(next: boolean) {
  if (saving.value || !auth.account) return;
  saving.value = true;
  try {
    auth.account = await identityService.updateAccount({ [props.field]: next });
    if (props.field === "show_presence") {
      // The choice travels in the access token: take a fresh one and reopen the
      // socket so peers see the change now, not at the next token refresh.
      await refreshSession(tokenStore.access);
      realtime.close();
      realtime.connect();
    }
    toasts.success(props.savedText);
  } catch (e) {
    toasts.error(e);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <SettingSwitch
    :model-value="value"
    :label="label"
    :hint="hint"
    :disabled="saving || !auth.account"
    :testid="`toggle-${field}`"
    @update:model-value="change"
  />
</template>
