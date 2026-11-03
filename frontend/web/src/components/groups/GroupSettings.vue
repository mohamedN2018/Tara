<script setup lang="ts">
import { Trash2 } from "lucide-vue-next";
import { reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { mediaErrorKey } from "@/lib/errors";
import { type Group, GROUP_ERRORS, type GroupFormValue, groupChanges, groupsService } from "@/services/groups";
import { useToastStore } from "@/stores/toasts";

import GroupFields from "./GroupFields.vue";

// Name, description, category, cover, privacy and approvals. Owners can also
// delete the group. The handle (the group's URL) never changes.
const props = defineProps<{ group: Group }>();
const emit = defineEmits<{ saved: [group: Group] }>();

const { t } = useI18n();
const router = useRouter();
const toasts = useToastStore();
const saving = ref(false);
const uploading = ref(false);

function fromGroup(g: Group): GroupFormValue {
  return {
    name: g.name,
    description: g.description,
    category: g.category,
    privacy: g.privacy,
    membership_approval: g.membership_approval,
    post_approval: g.post_approval,
    cover_media_id: g.cover_media_id,
  };
}
const value = reactive<GroupFormValue>(fromGroup(props.group));
watch(
  () => props.group,
  (g) => Object.assign(value, fromGroup(g)),
);

async function save() {
  const changes = groupChanges(value, props.group);
  if (!Object.keys(changes).length) {
    toasts.success(t("groups.settings.noChanges"));
    return;
  }
  if (changes.privacy && !window.confirm(t("groups.settings.privacyConfirm", { privacy: t(`groups.privacy.${changes.privacy}`) }))) return;
  saving.value = true;
  try {
    const saved = await groupsService.update(props.group.handle || props.group.id, changes);
    toasts.success(t("groups.settings.saved"));
    emit("saved", saved);
  } catch (e) {
    const media = mediaErrorKey(e);
    if (media) toasts.push({ text: t(media), icon: "error" });
    else toasts.error(e, GROUP_ERRORS);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!window.confirm(t("groups.settings.deleteConfirm", { name: props.group.name }))) return;
  saving.value = true;
  try {
    await groupsService.remove(props.group.handle || props.group.id);
    toasts.success(t("groups.settings.deleted"));
    router.replace("/groups?tab=mine");
  } catch (e) {
    toasts.error(e, GROUP_ERRORS);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <form class="space-y-4" novalidate @submit.prevent="save">
    <GroupFields
      v-model="value"
      id-prefix="group-settings"
      :can-change-privacy="group.viewer.can.change_privacy"
      @uploading="uploading = $event"
    />
    <div class="flex flex-wrap items-center gap-2">
      <button v-if="group.viewer.can.delete" type="button" class="btn-ghost text-red-600 dark:text-red-400" :disabled="saving" @click="remove">
        <Trash2 class="h-4 w-4" aria-hidden="true" /> {{ t("groups.settings.delete") }}
      </button>
      <button type="submit" class="btn-gradient ms-auto" :disabled="saving || uploading">{{ t("groups.settings.save") }}</button>
    </div>
  </form>
</template>
