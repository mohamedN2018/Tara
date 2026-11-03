<script setup lang="ts">
import { X } from "lucide-vue-next";
import { computed, defineAsyncComponent, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import AppShell from "@/components/layout/AppShell.vue";
import PostCard from "@/components/post/PostCard.vue";
import ProfileDetails from "@/components/profile/ProfileDetails.vue";
import ProfileFriendsTab from "@/components/profile/ProfileFriendsTab.vue";
import ProfileHero from "@/components/profile/ProfileHero.vue";
import ProfilePhotosTab from "@/components/profile/ProfilePhotosTab.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { useProfile } from "@/lib/useProfile";
import type { Profile } from "@/types";

// Loaded only when the editor is opened (keeps the profile bundle small).
const EditProfileModal = defineAsyncComponent(
  () => import("@/components/profile/EditProfileModal.vue"),
);

const { t } = useI18n();
const p = reactive(useProfile());

const lightbox = ref<string | null>(null);
const lightboxEl = ref<HTMLElement | null>(null);
useFocusTrap(lightboxEl);
useEscapeKey(
  computed(() => !!lightbox.value),
  () => (lightbox.value = null),
);

function onRemoved(id: string) {
  p.posts = p.posts.filter((post) => post.id !== id);
}

const showEdit = ref(false);
function onProfileSaved(fresh: Profile) {
  p.profile = fresh;
  showEdit.value = false;
}
</script>

<template>
  <AppShell :right="false">
    <div class="mx-auto w-full max-w-[1100px]">
      <div v-if="p.loading" class="card overflow-hidden">
        <div class="h-40 animate-pulse bg-gray-200 dark:bg-gray-800 sm:h-56" />
        <div class="px-4 pb-4">
          <div class="-mt-14 h-28 w-28 animate-pulse rounded-full border-4 border-white bg-gray-200 dark:border-gray-900 dark:bg-gray-700 sm:-mt-16" />
          <div class="mt-3 h-6 w-44 animate-pulse rounded bg-gray-200 dark:bg-gray-800" />
          <div class="mt-2 h-4 w-28 animate-pulse rounded bg-gray-200 dark:bg-gray-800" />
        </div>
      </div>

      <ErrorState v-else-if="p.error" :message="p.error" @retry="p.load" />

      <template v-else>
        <ProfileHero :state="p" @edit="showEdit = true" />

        <!-- Posts overview: details sidebar (always visible) + feed -->
        <div v-show="p.tab === 'posts'" class="mt-4">
          <EmptyState v-if="p.profile?.restricted">{{ t("profile.private") }}</EmptyState>
          <div v-else class="gap-4 xl:grid xl:grid-cols-[360px_minmax(0,1fr)] xl:items-start">
            <ProfileDetails :state="p" @edit="showEdit = true" @open-photo="lightbox = $event" />

            <!-- Feed -->
            <div class="mt-4 space-y-4 xl:mt-0">
              <LoadingSkeleton v-if="p.loadingPosts && !p.posts.length" :rows="2" />
              <ErrorState v-else-if="p.postsError" @retry="p.loadPosts" />
              <EmptyState v-else-if="p.posts.length === 0">{{ t("feed.empty") }}</EmptyState>
              <PostCard
                v-for="post in p.posts"
                :key="post.id"
                :post="post"
                :author-name="p.displayName"
                :author-handle="p.profile?.handle"
                :author-avatar="p.profile?.avatar_media_id"
                @removed="onRemoved"
              />
              <div v-if="p.hasMore" class="flex justify-center pt-1">
                <button class="btn-ghost" :disabled="p.loadingMore" @click="p.loadMore">
                  {{ p.loadingMore ? t("states.loading") : t("feed.loadMore") }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <ProfilePhotosTab v-show="p.tab === 'photos'" class="mt-4" :state="p" @open-photo="lightbox = $event" />
        <ProfileFriendsTab v-show="p.tab === 'friends'" class="mt-4" :state="p" />
      </template>
    </div>

    <!-- Lightbox -->
    <div
      v-if="lightbox"
      ref="lightboxEl"
      class="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 p-4"
      role="dialog"
      aria-modal="true"
      :aria-label="t('profile.enlargedPhoto')"
      tabindex="-1"
      @click="lightbox = null"
    >
      <button class="absolute end-4 top-4 rounded-full bg-white/15 p-2 text-white" :aria-label="t('profile.closePhoto')">
        <X class="h-5 w-5" />
      </button>
      <img :src="lightbox" class="max-h-[90vh] max-w-full rounded-lg object-contain" :alt="t('profile.enlargedPhoto')" />
    </div>

    <EditProfileModal v-if="showEdit && p.profile" :profile="p.profile" @close="showEdit = false" @saved="onProfileSaved" />
  </AppShell>
</template>
