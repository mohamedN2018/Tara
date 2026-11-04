<script setup lang="ts">
import { Trash2 } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { errorMessage } from "@/lib/errors";
import { canManagePage, PAGE_ROLES, type Page, type PageMember, pageService } from "@/services/pages";
import { profileService } from "@/services/profile";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

// The page's team (staff only): roles, add by handle, remove, leave.
const props = defineProps<{ page: Page }>();

const { t } = useI18n();
const router = useRouter();
const auth = useAuthStore();
const directory = useDirectoryStore();
const toasts = useToastStore();

const members = ref<PageMember[]>([]);
const loading = ref(true);
const error = ref(false);
const canManage = computed(() => canManagePage(props.page));

async function load() {
  loading.value = true;
  error.value = false;
  try {
    members.value = await pageService.members(props.page.id);
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

const newHandle = ref("");
const newRole = ref("editor");
const adding = ref(false);
const memberError = ref("");

async function addMember() {
  if (adding.value || !newHandle.value.trim()) return;
  adding.value = true;
  memberError.value = "";
  try {
    const profile = await profileService.get(newHandle.value.trim().replace(/^@/, ""));
    if (!profile.account_id) throw new Error("no account");
    members.value.push(await pageService.addMember(props.page.id, profile.account_id, newRole.value));
    newHandle.value = "";
  } catch (e) {
    memberError.value = errorMessage(e, { not_found: "pages.memberNotFound", conflict: "pages.alreadyMember" });
  } finally {
    adding.value = false;
  }
}

async function setRole(member: PageMember, role: string) {
  const previous = member.role;
  member.role = role;
  try {
    await pageService.setRole(props.page.id, member.id, role);
  } catch (e) {
    member.role = previous;
    toasts.error(e);
  }
}

async function remove(member: PageMember) {
  try {
    await pageService.removeMember(props.page.id, member.id);
    if (member.account_id === auth.account?.id) {
      router.push({ name: "pages" });
      return;
    }
    members.value = members.value.filter((m) => m.id !== member.id);
  } catch (e) {
    toasts.error(e);
  }
}

onMounted(load);
</script>

<template>
  <section class="card p-4 sm:p-5" aria-labelledby="page-team-title">
    <h2 id="page-team-title" class="mb-3 text-xl font-bold">{{ t("pages.team") }}</h2>
    <LoadingSkeleton v-if="loading" :rows="2" />
    <ErrorState v-else-if="error" @retry="load" />
    <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800" data-testid="page-members">
      <li v-for="m in members" :key="m.id" class="flex items-center gap-3 py-2.5">
        <UserAvatar :name="directory.label(m.account_id)" :media-id="directory.avatarOf(m.account_id)" :size="40" />
        <RouterLink :to="{ name: 'profile-by-id', params: { id: m.account_id } }" class="min-w-0 flex-1 truncate text-sm font-semibold hover:underline" dir="auto">
          {{ directory.label(m.account_id) }}
        </RouterLink>
        <select
          v-if="canManage && m.role !== 'owner'"
          :value="m.role"
          class="input w-auto py-1 text-sm"
          :aria-label="t('pages.roleOf', { name: directory.label(m.account_id) })"
          @change="setRole(m, ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="r in PAGE_ROLES" :key="r" :value="r">{{ t(`pages.roles.${r}`) }}</option>
        </select>
        <span v-else class="text-xs text-gray-500 dark:text-gray-400">{{ t(`pages.roles.${m.role}`) }}</span>
        <button
          v-if="m.role !== 'owner' && (canManage || m.account_id === auth.account?.id)"
          type="button"
          class="rounded-full p-1.5 text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40"
          :aria-label="m.account_id === auth.account?.id ? t('pages.leave') : t('pages.removeMember')"
          @click="remove(m)"
        >
          <Trash2 class="h-4 w-4" aria-hidden="true" />
        </button>
      </li>
    </ul>

    <form v-if="canManage" class="mt-4 flex flex-wrap gap-2" @submit.prevent="addMember">
      <input v-model="newHandle" class="input min-w-40 flex-1" dir="ltr" :placeholder="t('pages.memberHandle')" :aria-label="t('pages.memberHandle')" />
      <select v-model="newRole" class="input w-auto" :aria-label="t('pages.memberRole')">
        <option v-for="r in PAGE_ROLES" :key="r" :value="r">{{ t(`pages.roles.${r}`) }}</option>
      </select>
      <button type="submit" class="btn-primary" :disabled="adding || !newHandle.trim()">{{ t("pages.addMember") }}</button>
    </form>
    <p v-if="memberError" class="mt-2 text-sm text-red-600 dark:text-red-400" role="alert">{{ memberError }}</p>
  </section>
</template>
