<script setup lang="ts">
import { MapPin, MessageCircle } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import AppShell from "@/components/layout/AppShell.vue";
import PostCard from "@/components/post/PostCard.vue";
import FollowButton from "@/components/social/FollowButton.vue";
import FriendButton from "@/components/social/FriendButton.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { useMediaUrl } from "@/lib/useMediaUrl";
import type { FriendState } from "@/services/graph";
import { chatService } from "@/services/chat";
import { postService } from "@/services/post";
import { profileService } from "@/services/profile";
import type { Post, Profile } from "@/types";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();

const profile = ref<Profile | null>(null);
const posts = ref<Post[]>([]);
const loading = ref(true);
const error = ref(false);

const cover = useMediaUrl(() => profile.value?.cover_media_id);
const userId = computed(() => profile.value?.user_id ?? profile.value?.id ?? null);
const isSelf = computed(() => profile.value?.is_self ?? false);
const friendState = computed<FriendState>(() => (profile.value?.are_friends ? "friends" : "none"));

async function load() {
  loading.value = true;
  error.value = false;
  const handle = route.params.handle as string;
  try {
    profile.value = await profileService.get(handle);
    if (userId.value && !profile.value.restricted) {
      const page = await postService.byAuthor(userId.value);
      posts.value = page.data;
    } else {
      posts.value = [];
    }
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

async function message() {
  if (!userId.value) return;
  const convo = await chatService.openDm(userId.value);
  router.push(`/messages/${convo.id}`);
}

watch(() => route.params.handle, load, { immediate: true });
</script>

<template>
  <AppShell>
    <LoadingSkeleton v-if="loading" :rows="2" />
    <ErrorState v-else-if="error || !profile" @retry="load" />

    <template v-else>
      <div class="card overflow-hidden">
        <div class="h-32 bg-gradient-to-r from-brand-400 to-brand-600">
          <img v-if="cover" :src="cover" class="h-full w-full object-cover" alt="" />
        </div>
        <div class="px-4 pb-4">
          <div class="-mt-10 flex items-end justify-between">
            <UserAvatar
              :name="profile.display_name"
              :media-id="profile.avatar_media_id"
              :size="80"
            />
            <div class="mb-1 flex items-center gap-2">
              <template v-if="isSelf">
                <RouterLink to="/settings" class="btn-ghost">{{ t("profile.editProfile") }}</RouterLink>
              </template>
              <template v-else-if="userId">
                <FollowButton :user-id="userId" :following="false" />
                <FriendButton :user-id="userId" :state="friendState" />
                <button class="btn-ghost px-2" @click="message">
                  <MessageCircle class="h-4 w-4" />
                </button>
              </template>
            </div>
          </div>

          <h1 class="mt-2 text-xl font-bold">{{ profile.display_name }}</h1>
          <p class="text-sm text-gray-500">@{{ profile.handle }}</p>
          <p v-if="profile.bio" class="mt-2 text-sm">{{ profile.bio }}</p>
          <p
            v-if="profile.city || profile.country"
            class="mt-1 flex items-center gap-1 text-xs text-gray-500"
          >
            <MapPin class="h-3 w-3" /> {{ [profile.city, profile.country].filter(Boolean).join(", ") }}
          </p>
        </div>
      </div>

      <div class="mt-4 space-y-4">
        <EmptyState v-if="profile.restricted">{{ t("profile.private") }}</EmptyState>
        <EmptyState v-else-if="posts.length === 0">{{ t("feed.empty") }}</EmptyState>
        <PostCard
          v-for="post in posts"
          v-else
          :key="post.id"
          :post="post"
          :author-name="profile.display_name"
          :author-handle="profile.handle"
          :author-avatar="profile.avatar_media_id"
        />
      </div>
    </template>
  </AppShell>
</template>
