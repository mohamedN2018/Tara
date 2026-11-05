<script setup lang="ts">
import { X } from "lucide-vue-next";
import { computed, defineAsyncComponent, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import AppShell from "@/components/layout/AppShell.vue";
import CreatePostCard from "@/components/post/CreatePostCard.vue";
import PostCard from "@/components/post/PostCard.vue";
import ProfileAboutTab from "@/components/profile/ProfileAboutTab.vue";
import ProfileDetails from "@/components/profile/ProfileDetails.vue";
import ProfileFriendsTab from "@/components/profile/ProfileFriendsTab.vue";
import ProfileHero from "@/components/profile/ProfileHero.vue";
import ProfilePhotosTab from "@/components/profile/ProfilePhotosTab.vue";
import ReelGrid from "@/components/reels/ReelGrid.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { useProfile } from "@/lib/useProfile";
import type { Post, Profile } from "@/types";

// Loaded only when the editor is opened (keeps the profile bundle small).
const EditProfileModal = defineAsyncComponent(
  () => import("@/components/profile/EditProfileModal.vue"),
);
// The person's shop (marketplace listings and reviews), only when they have one.
const SellerShop = defineAsyncComponent(() => import("@/components/marketplace/SellerShop.vue"));

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
function onCreated(post: Post) {
  if (post.author_id === p.userId) p.posts = [post, ...p.posts];
}

const showEdit = ref(false);
function onProfileSaved(fresh: Profile) {
  p.profile = fresh;
  showEdit.value = false;
}
</script>

<template>
  <AppShell :left="false" :right="false">
    <!-- The reference keeps the header and body on one ~940px column, centred. -->
    <div class="mx-auto w-full max-w-[960px]">
      <div v-if="p.loading" class="card overflow-hidden">
        <div class="h-44 animate-pulse bg-gray-200 dark:bg-gray-800 sm:h-64 lg:h-[22rem]" />
        <div class="px-4 pb-4 sm:px-8">
          <div class="-mt-20 h-40 w-40 animate-pulse rounded-full border-4 border-white bg-gray-200 dark:border-gray-900 dark:bg-gray-700" />
          <div class="mt-3 h-7 w-52 animate-pulse rounded bg-gray-200 dark:bg-gray-800" />
          <div class="mt-2 h-4 w-32 animate-pulse rounded bg-gray-200 dark:bg-gray-800" />
        </div>
      </div>

      <ErrorState v-else-if="p.error" :message="p.error" @retry="p.load" />

      <template v-else>
        <ProfileHero :state="p" @edit="showEdit = true" @open-photo="lightbox = $event" />

        <EmptyState v-if="p.profile?.restricted" class="card mt-4">{{ t("profile.private") }}</EmptyState>
        <template v-else>
          <!-- Posts: details column (start) + timeline (end), as in the reference -->
          <div v-show="p.tab === 'posts'" class="mt-4 gap-4 lg:grid lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:items-start">
            <ProfileDetails :state="p" @edit="showEdit = true" @open-photo="lightbox = $event" />

            <div class="mt-4 space-y-4 lg:mt-0">
              <CreatePostCard v-if="p.isSelf" :listen-shortcuts="false" @created="onCreated" />
              <div class="card flex items-center justify-between px-4 py-3">
                <h2 class="text-xl font-bold">{{ t("people.posts.title") }}</h2>
              </div>
              <LoadingSkeleton v-if="p.loadingPosts && !p.posts.length" :rows="2" />
              <ErrorState v-else-if="p.postsError" @retry="p.loadPosts" />
              <EmptyState v-else-if="p.posts.length === 0" class="card">{{ t("feed.empty") }}</EmptyState>
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

          <ProfileAboutTab v-if="p.tab === 'about'" class="mt-4" :state="p" />
          <ProfilePhotosTab v-show="p.tab === 'photos'" class="mt-4" :state="p" @open-photo="lightbox = $event" />
          <ProfileFriendsTab v-show="p.tab === 'friends'" class="mt-4" :state="p" />
          <ReelGrid v-if="p.tab === 'reels' && p.userId" class="mt-4" :author-id="p.userId" :can-create="p.isSelf" />
          <SellerShop
            v-if="p.tab === 'marketplace' && p.hasShop && p.userId"
            class="mt-4"
            :seller-id="p.userId"
            :summary="false"
            data-testid="profile-marketplace"
          />
        </template>
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
