<script setup lang="ts">
import { KeyRound, X } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import ErrorState from "@/components/states/ErrorState.vue";
import { adminService, type RoleHolder } from "@/services/admin";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";

const ROLES = ["admin", "moderator", "ad_reviewer", "analyst"];
const { t } = useI18n();
const auth = useAuthStore();
const toasts = useToastStore();

const holders = ref<RoleHolder[]>([]);
const error = ref(false);
const email = ref("");
const role = ref("moderator");
const busy = ref(false);

async function load() {
  error.value = false;
  try {
    holders.value = await adminService.roleHolders();
  } catch {
    error.value = true;
  }
}

async function grant() {
  if (busy.value || !email.value.trim()) return;
  busy.value = true;
  try {
    const account = await adminService.findAccount(email.value.trim());
    await adminService.grantRole(account.account_id, role.value);
    email.value = "";
    await load();
  } catch (e) {
    toasts.error(e, { not_found: "admin.accountNotFound" });
  } finally {
    busy.value = false;
  }
}

async function revoke(holder: RoleHolder, name: string) {
  try {
    await adminService.revokeRole(holder.account_id, name);
    await load();
  } catch (e) {
    toasts.error(e);
  }
}

const removable = (holder: RoleHolder, name: string) =>
  !holder.bridged_roles.includes(name) &&
  !(name === "admin" && holder.account_id === auth.account?.id);

onMounted(load);
</script>

<template>
  <section class="mb-6">
    <h2 class="mb-1 flex items-center gap-2 font-semibold">
      <KeyRound class="h-5 w-5 text-brand-600" /> {{ t("admin.roles") }}
    </h2>
    <p class="mb-2 text-xs text-gray-500">{{ t("admin.rolesHint") }}</p>
    <ErrorState v-if="error" @retry="load" />
    <template v-else>
      <ul class="space-y-2" data-testid="role-holders">
        <li v-for="holder in holders" :key="holder.account_id" class="card flex flex-wrap items-center gap-2 p-3">
          <span class="min-w-0 flex-1 truncate text-sm" dir="ltr">{{ holder.email }}</span>
          <span
            v-for="name in holder.roles"
            :key="name"
            class="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-800"
          >
            {{ t(`admin.roleNames.${name}`) }}
            <button
              v-if="removable(holder, name)"
              class="rounded-full text-gray-400 hover:text-red-500"
              :aria-label="t('admin.revokeRole', { role: t(`admin.roleNames.${name}`), email: holder.email })"
              @click="revoke(holder, name)"
            >
              <X class="h-3 w-3" />
            </button>
          </span>
        </li>
      </ul>
      <form class="mt-2 flex flex-wrap gap-2" @submit.prevent="grant">
        <input v-model="email" class="input min-w-48 flex-1" type="email" dir="ltr" required :aria-label="t('admin.accountEmail')" :placeholder="t('admin.accountEmail')" />
        <select v-model="role" class="input w-auto" :aria-label="t('admin.role')">
          <option v-for="r in ROLES" :key="r" :value="r">{{ t(`admin.roleNames.${r}`) }}</option>
        </select>
        <button class="btn-primary shrink-0" :disabled="busy">{{ t("admin.grantRole") }}</button>
      </form>
    </template>
  </section>
</template>
