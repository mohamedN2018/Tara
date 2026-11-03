<script setup lang="ts">
import { Ban, Check, Search, UserMinus, Undo2, X } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { useAuthStore } from "@/stores/auth";
import {
  assignableRoles,
  canActOn,
  type Group,
  GROUP_ERRORS,
  GROUP_ROLES,
  type GroupRole,
  groupsService,
  type Membership,
  type MemberState,
} from "@/services/groups";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";

// Members by state. With `manage`, staff get the controls their role allows
// (the server checks every one again): approve or decline requests, change
// roles, remove, ban and unban.
const props = withDefaults(defineProps<{ group: Group; state?: MemberState; manage?: boolean }>(), {
  state: "active",
  manage: false,
});
const emit = defineEmits<{ changed: [] }>();

const { t } = useI18n();
const auth = useAuthStore();
const directory = useDirectoryStore();
const toasts = useToastStore();

const rows = ref<Membership[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
const role = ref<GroupRole | "">("");
const query = ref("");
const busy = ref<string | null>(null);
let generation = 0;

const me = computed(() => auth.account?.id ?? "");
const myRole = computed(() => props.group.viewer.role);
const groupRef = computed(() => props.group.handle || props.group.id);

async function load() {
  const run = ++generation;
  loading.value = true;
  error.value = false;
  try {
    const page = await groupsService.members(groupRef.value, { state: props.state, role: role.value, q: query.value.trim() });
    if (run !== generation) return;
    rows.value = page.data;
    cursor.value = page.page.next_cursor;
  } catch {
    if (run === generation) error.value = true;
  } finally {
    if (run === generation) loading.value = false;
  }
}

async function loadMore() {
  if (!cursor.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await groupsService.members(groupRef.value, {
      state: props.state,
      role: role.value,
      q: query.value.trim(),
      cursor: cursor.value,
    });
    rows.value = [...rows.value, ...page.data];
    cursor.value = page.page.next_cursor;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

async function act(m: Membership, action: () => Promise<unknown>, success: string, keep = false) {
  if (busy.value) return;
  busy.value = m.account_id;
  try {
    await action();
    if (!keep) rows.value = rows.value.filter((r) => r.account_id !== m.account_id);
    toasts.success(success);
    emit("changed");
  } catch (e) {
    toasts.error(e, GROUP_ERRORS);
  } finally {
    busy.value = null;
  }
}

const name = (m: Membership) => directory.label(m.account_id);
const approve = (m: Membership) =>
  act(m, () => groupsService.approveRequest(groupRef.value, m.account_id), t("groups.members.approved", { name: name(m) }));
const decline = (m: Membership) =>
  act(m, () => groupsService.declineRequest(groupRef.value, m.account_id), t("groups.members.declined", { name: name(m) }));
function remove(m: Membership) {
  if (!window.confirm(t("groups.members.removeConfirm", { name: name(m) }))) return;
  act(m, () => groupsService.removeMember(groupRef.value, m.account_id), t("groups.members.removed", { name: name(m) }));
}
function ban(m: Membership) {
  if (!window.confirm(t("groups.members.banConfirm", { name: name(m) }))) return;
  act(m, () => groupsService.ban(groupRef.value, m.account_id), t("groups.members.banned", { name: name(m) }));
}
const unban = (m: Membership) =>
  act(m, () => groupsService.unban(groupRef.value, m.account_id), t("groups.members.unbanned", { name: name(m) }));

async function changeRole(m: Membership, next: GroupRole) {
  if (next === m.role) return;
  const before = m.role;
  m.role = next;
  await act(
    m,
    async () => {
      try {
        Object.assign(m, await groupsService.setRole(groupRef.value, m.account_id, next));
      } catch (e) {
        m.role = before;
        throw e;
      }
    },
    t("groups.members.roleChanged", { name: name(m), role: t(`groups.roles.${next}`) }),
    true,
  );
}

let searchTimer: number | undefined;
watch(query, () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(load, 300);
});
watch(() => [props.group.id, props.state, role.value], load);
onMounted(load);
</script>

<template>
  <div class="space-y-3">
    <div v-if="state === 'active'" class="flex flex-wrap gap-2">
      <label class="relative min-w-40 flex-1">
        <span class="sr-only">{{ t("groups.members.search") }}</span>
        <Search class="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden="true" />
        <input v-model="query" type="search" class="input ps-9" :placeholder="t('groups.members.search')" dir="auto" maxlength="60" />
      </label>
      <label>
        <span class="sr-only">{{ t("groups.members.roleFilter") }}</span>
        <select v-model="role" class="input w-auto">
          <option value="">{{ t("groups.members.allRoles") }}</option>
          <option v-for="r in GROUP_ROLES" :key="r" :value="r">{{ t(`groups.roles.${r}`) }}</option>
        </select>
      </label>
    </div>

    <LoadingSkeleton v-if="loading" :rows="3" />
    <ErrorState v-else-if="error" @retry="load" />
    <EmptyState v-else-if="!rows.length">{{ t(`groups.empty.members_${state}`) }}</EmptyState>
    <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800">
      <li v-for="m in rows" :key="m.account_id" class="flex flex-wrap items-center gap-3 py-2.5" data-testid="group-member">
        <RouterLink :to="{ name: 'profile-by-id', params: { id: m.account_id } }" class="flex min-w-0 flex-1 items-center gap-3">
          <UserAvatar :name="name(m)" :media-id="directory.avatarOf(m.account_id)" :size="40" />
          <span class="min-w-0">
            <span class="block truncate text-sm font-semibold" dir="auto">{{ name(m) }}</span>
            <span class="block text-xs text-gray-500 dark:text-gray-400">{{ t(`groups.roles.${m.role}`) }}</span>
          </span>
        </RouterLink>

        <template v-if="manage && m.account_id !== me">
          <div v-if="state === 'requested' && group.viewer.can.approve_requests" class="flex gap-2">
            <button type="button" class="btn-outline" :disabled="busy === m.account_id" :aria-label="t('groups.members.declineNamed', { name: name(m) })" @click="decline(m)">
              <X class="h-4 w-4" aria-hidden="true" /> {{ t("groups.members.decline") }}
            </button>
            <button type="button" class="btn-primary" :disabled="busy === m.account_id" :aria-label="t('groups.members.approveNamed', { name: name(m) })" @click="approve(m)">
              <Check class="h-4 w-4" aria-hidden="true" /> {{ t("groups.members.approve") }}
            </button>
          </div>

          <div v-else-if="state === 'active'" class="flex flex-wrap items-center gap-2">
            <label v-if="group.viewer.can.change_roles && assignableRoles(myRole, m.role).length">
              <span class="sr-only">{{ t("groups.members.roleFor", { name: name(m) }) }}</span>
              <select
                :value="m.role"
                class="input h-9 w-auto py-1 text-xs"
                :disabled="busy === m.account_id"
                @change="changeRole(m, ($event.target as HTMLSelectElement).value as GroupRole)"
              >
                <option v-for="r in assignableRoles(myRole, m.role)" :key="r" :value="r">{{ t(`groups.roles.${r}`) }}</option>
                <option v-if="!assignableRoles(myRole, m.role).includes(m.role)" :value="m.role" disabled>{{ t(`groups.roles.${m.role}`) }}</option>
              </select>
            </label>
            <template v-if="group.viewer.can.moderate && canActOn(myRole, m.role)">
              <button type="button" class="btn-ghost text-sm" :disabled="busy === m.account_id" :aria-label="t('groups.members.removeNamed', { name: name(m) })" @click="remove(m)">
                <UserMinus class="h-4 w-4" aria-hidden="true" /> {{ t("groups.members.remove") }}
              </button>
              <button type="button" class="btn-ghost text-sm text-red-600 dark:text-red-400" :disabled="busy === m.account_id" :aria-label="t('groups.members.banNamed', { name: name(m) })" @click="ban(m)">
                <Ban class="h-4 w-4" aria-hidden="true" /> {{ t("groups.members.ban") }}
              </button>
            </template>
          </div>

          <button
            v-else-if="state === 'banned' && group.viewer.can.moderate"
            type="button"
            class="btn-outline"
            :disabled="busy === m.account_id"
            :aria-label="t('groups.members.unbanNamed', { name: name(m) })"
            @click="unban(m)"
          >
            <Undo2 class="h-4 w-4" aria-hidden="true" /> {{ t("groups.members.unban") }}
          </button>
        </template>
      </li>
    </ul>
    <button v-if="!loading && cursor" class="btn-ghost mx-auto block" :disabled="loadingMore" @click="loadMore">
      {{ loadingMore ? t("states.loading") : t("states.loadMore") }}
    </button>
  </div>
</template>
