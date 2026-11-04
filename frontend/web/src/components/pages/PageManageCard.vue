<script setup lang="ts">
import { Eye, Link2, MoreHorizontal, PenSquare, Settings2, UsersRound } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { canEditPage, canPostAs, type Page } from "@/services/pages";
import { useToastStore } from "@/stores/toasts";

// A page in "Pages you manage": avatar, name, the viewer's role and the
// follower count, then the actions the role allows (the server checks again).
const props = defineProps<{ page: Page }>();
const emit = defineEmits<{ compose: [page: Page] }>();

const { t } = useI18n();
const toasts = useToastStore();
const menuOpen = ref(false);
useEscapeKey(menuOpen, () => (menuOpen.value = false));
const pageRoute = computed(() => ({ name: "page", params: { handle: props.page.handle } }));

async function copyLink() {
  menuOpen.value = false;
  try {
    await navigator.clipboard.writeText(new URL(`/pages/${props.page.handle}`, window.location.origin).href);
    toasts.success(t("pageHub.header.copied"));
  } catch {
    toasts.push({ text: t("errors.copyFailed"), icon: "error" });
  }
}
</script>

<template>
  <article class="card space-y-3 p-4" data-testid="page-manage-card" :aria-labelledby="`page-card-${page.id}`">
    <div class="flex items-center gap-3">
      <RouterLink :to="pageRoute" class="shrink-0" :aria-label="page.name">
        <span class="avatar-ring block p-0.5">
          <span class="block rounded-full border-2 border-white dark:border-gray-900">
            <UserAvatar :name="page.name" :media-id="page.avatar_media_id" :size="60" />
          </span>
        </span>
      </RouterLink>
      <div class="min-w-0 flex-1">
        <RouterLink :id="`page-card-${page.id}`" :to="pageRoute" class="block truncate text-lg font-bold hover:underline" data-testid="page-card-name">
          <bdi>{{ page.name }}</bdi>
        </RouterLink>
        <p class="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-gray-500 dark:text-gray-400">
          <span v-if="page.my_role" class="inline-flex items-center gap-1">
            <span class="h-2 w-2 rounded-full bg-brand-500" aria-hidden="true" />
            {{ t(`pages.roles.${page.my_role}`) }}
          </span>
          <span v-if="page.followers_count !== null" class="inline-flex items-center gap-1">
            <UsersRound class="h-4 w-4" aria-hidden="true" />
            {{ t("pageHub.card.followers", { count: page.followers_count }, page.followers_count) }}
          </span>
          <span v-if="page.status !== 'published'" class="font-medium text-amber-600 dark:text-amber-400">{{ t(`pages.status.${page.status}`) }}</span>
        </p>
      </div>
    </div>

    <div class="flex items-stretch gap-2">
      <button
        v-if="canPostAs(page)"
        type="button"
        class="btn-primary flex-1"
        data-testid="page-card-compose"
        @click="emit('compose', page)"
      >
        <PenSquare class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.card.createPost") }}
      </button>
      <RouterLink
        v-if="canEditPage(page)"
        :to="{ name: 'page', params: { handle: page.handle }, query: { edit: '1' } }"
        class="btn-soft flex-1"
      >
        <Settings2 class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.card.edit") }}
      </RouterLink>
      <RouterLink v-else :to="pageRoute" class="btn-soft flex-1">
        <Eye class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.card.view") }}
      </RouterLink>
      <div class="relative">
        <button
          type="button"
          class="btn-ghost h-full bg-gray-100 px-3 dark:bg-gray-800"
          :aria-label="t('pageHub.card.more', { name: page.name })"
          aria-haspopup="menu"
          :aria-expanded="menuOpen"
          @click="menuOpen = !menuOpen"
        >
          <MoreHorizontal class="h-5 w-5" aria-hidden="true" />
        </button>
        <template v-if="menuOpen">
          <div class="fixed inset-0 z-40" @click="menuOpen = false" />
          <div class="popover absolute end-0 z-50 mt-1 w-52 p-1" role="menu">
            <RouterLink :to="pageRoute" role="menuitem" class="nav-item w-full" @click="menuOpen = false">
              <Eye class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.card.view") }}
            </RouterLink>
            <RouterLink
              :to="{ name: 'page', params: { handle: page.handle }, query: { tab: 'team' } }"
              role="menuitem"
              class="nav-item w-full"
              @click="menuOpen = false"
            >
              <UsersRound class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.card.team") }}
            </RouterLink>
            <button type="button" role="menuitem" class="nav-item w-full" @click="copyLink">
              <Link2 class="h-4 w-4" aria-hidden="true" /> {{ t("pageHub.header.copyLink") }}
            </button>
          </div>
        </template>
      </div>
    </div>
  </article>
</template>
