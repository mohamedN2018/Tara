<script setup lang="ts">
import { Flag, MapPin, Trash2 } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { apiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { PAGE_ROLES, type Page, type PageMember, pageService } from "@/services/pages";
import { profileService } from "@/services/profile";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const directory = useDirectoryStore();
const toasts = useToastStore();

const page = ref<Page | null>(null);
const members = ref<PageMember[]>([]);
const loading = ref(true);
const notFound = ref(false);
const error = ref(false);

const canManage = computed(() => ["owner", "admin"].includes(page.value?.my_role ?? ""));
const canEdit = computed(() => canManage.value || page.value?.my_role === "editor");

async function load() {
  loading.value = true;
  notFound.value = false;
  error.value = false;
  try {
    page.value = await pageService.get(route.params.handle as string);
    Object.assign(form.value, page.value);
    members.value = page.value.my_role ? await pageService.members(page.value.id) : [];
  } catch (e) {
    if (apiError(e).code === "not_found") notFound.value = true;
    else error.value = true;
  } finally {
    loading.value = false;
  }
}

// ---- edit ----
const editing = ref(false);
const saving = ref(false);
const form = ref({ name: "", category: "", location: "", description: "", status: "published" });

async function save() {
  if (!page.value || saving.value) return;
  saving.value = true;
  const { name, category, location, description, status } = form.value;
  try {
    page.value = await pageService.update(page.value.id, {
      name,
      category,
      location,
      description,
      ...(canManage.value ? { status } : {}),
    });
    editing.value = false;
  } catch (e) {
    toasts.error(e);
  } finally {
    saving.value = false;
  }
}

// ---- members ----
const newHandle = ref("");
const newRole = ref("editor");
const adding = ref(false);
const memberError = ref("");

async function addMember() {
  if (!page.value || adding.value || !newHandle.value.trim()) return;
  adding.value = true;
  memberError.value = "";
  try {
    const profile = await profileService.get(newHandle.value.trim().replace(/^@/, ""));
    if (!profile.account_id) throw new Error("no account");
    members.value.push(await pageService.addMember(page.value.id, profile.account_id, newRole.value));
    newHandle.value = "";
  } catch (e) {
    memberError.value = errorMessage(e, { not_found: "pages.memberNotFound", conflict: "pages.alreadyMember" });
  } finally {
    adding.value = false;
  }
}

async function setRole(member: PageMember, role: string) {
  if (!page.value) return;
  const previous = member.role;
  member.role = role;
  try {
    await pageService.setRole(page.value.id, member.id, role);
  } catch (e) {
    member.role = previous;
    toasts.error(e);
  }
}

async function remove(member: PageMember) {
  if (!page.value) return;
  try {
    await pageService.removeMember(page.value.id, member.id);
    if (member.account_id === auth.account?.id) {
      router.push({ name: "pages" });
      return;
    }
    members.value = members.value.filter((m) => m.id !== member.id);
  } catch (e) {
    toasts.error(e);
  }
}

watch(() => route.params.handle, (handle) => handle && load(), { immediate: true });
</script>

<template>
  <AppShell>
    <div class="mx-auto w-full max-w-[720px] space-y-4">
      <LoadingSkeleton v-if="loading" :rows="3" />
      <p v-else-if="notFound" class="card p-6 text-center text-sm text-gray-500 dark:text-gray-400">{{ t("pages.notFound") }}</p>
      <ErrorState v-else-if="error || !page" @retry="load" />
      <template v-else>
        <section class="card p-5">
          <div class="flex items-start gap-3">
            <span class="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-950/50 dark:text-brand-300">
              <Flag class="h-7 w-7" />
            </span>
            <div class="min-w-0 flex-1">
              <h1 class="truncate text-xl font-bold" dir="auto" data-testid="page-name">{{ page.name }}</h1>
              <p class="text-sm text-gray-500 dark:text-gray-400" dir="ltr">@{{ page.handle }}</p>
              <p v-if="page.category" class="text-sm text-gray-500 dark:text-gray-400" dir="auto">{{ page.category }}</p>
              <p v-if="page.status !== 'published'" class="mt-1 text-xs font-medium text-amber-600">{{ t(`pages.status.${page.status}`) }}</p>
            </div>
            <button v-if="canEdit && !editing" class="btn-ghost" @click="editing = true">{{ t("post.edit") }}</button>
          </div>
          <p v-if="page.description && !editing" class="mt-4 whitespace-pre-wrap break-words text-sm" dir="auto">{{ page.description }}</p>
          <p v-if="page.location && !editing" class="mt-2 flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400" dir="auto">
            <MapPin class="h-4 w-4" /> {{ page.location }}
          </p>

          <form v-if="editing" class="mt-4 space-y-3" @submit.prevent="save">
            <input v-model="form.name" class="input" dir="auto" maxlength="120" required :aria-label="t('pages.name')" />
            <input v-model="form.category" class="input" dir="auto" maxlength="80" :aria-label="t('pages.category')" :placeholder="t('pages.category')" />
            <input v-model="form.location" class="input" dir="auto" maxlength="160" :aria-label="t('pages.location')" :placeholder="t('pages.location')" />
            <textarea v-model="form.description" class="input min-h-20" dir="auto" rows="3" :aria-label="t('pages.description')" :placeholder="t('pages.description')" />
            <select v-if="canManage && page.status !== 'suspended'" v-model="form.status" class="input" :aria-label="t('pages.statusLabel')">
              <option value="published">{{ t("pages.status.published") }}</option>
              <option value="draft">{{ t("pages.status.draft") }}</option>
            </select>
            <div class="flex justify-end gap-2">
              <button type="button" class="btn-ghost" @click="editing = false">{{ t("feed.cancel") }}</button>
              <button type="submit" class="btn-primary" :disabled="saving">{{ t("settings.save") }}</button>
            </div>
          </form>
        </section>

        <section v-if="page.my_role" class="card p-5">
          <h2 class="mb-3 font-semibold">{{ t("pages.team") }}</h2>
          <ul class="space-y-2" data-testid="page-members">
            <li v-for="m in members" :key="m.id" class="flex items-center gap-3">
              <UserAvatar :name="directory.label(m.account_id)" :media-id="directory.avatarOf(m.account_id)" :size="32" />
              <RouterLink :to="{ name: 'profile-by-id', params: { id: m.account_id } }" class="min-w-0 flex-1 truncate text-sm hover:underline" dir="auto">
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
                class="rounded-full p-1 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40"
                :aria-label="m.account_id === auth.account?.id ? t('pages.leave') : t('pages.removeMember')"
                @click="remove(m)"
              >
                <Trash2 class="h-4 w-4" />
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
          <p v-if="memberError" class="mt-2 text-sm text-red-500">{{ memberError }}</p>
        </section>
      </template>
    </div>
  </AppShell>
</template>
