<script setup lang="ts">
import UserAvatar from "@/components/common/UserAvatar.vue";
import { useMediaUrl } from "@/lib/useMediaUrl";
import { useDirectoryStore } from "@/stores/directory";

// The top of a person card in the Friends hub: the profile photo edge to edge,
// or the initials avatar on a brand gradient when there is no photo. The link
// is decorative (the name below is the real link), so it stays out of the tab
// order and the a11y tree.
const props = defineProps<{ accountId: string }>();
const directory = useDirectoryStore();
const url = useMediaUrl(() => directory.avatarOf(props.accountId));
</script>

<template>
  <RouterLink
    :to="{ name: 'profile-by-id', params: { id: accountId } }"
    class="relative block aspect-square overflow-hidden bg-gradient-to-br from-brand-100 via-accent-50 to-brand-50 dark:from-brand-950/60 dark:via-gray-900 dark:to-brand-950/40"
    tabindex="-1"
    aria-hidden="true"
    data-testid="person-photo"
  >
    <img v-if="url" :src="url" alt="" class="h-full w-full object-cover" loading="lazy" decoding="async" />
    <span v-else class="flex h-full w-full items-center justify-center">
      <UserAvatar :name="directory.label(accountId)" :size="96" />
    </span>
  </RouterLink>
</template>
