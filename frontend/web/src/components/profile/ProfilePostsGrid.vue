<script setup lang="ts">
import { Clapperboard, Images, Play } from "lucide-vue-next";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { useMediaList } from "@/lib/useMediaList";
import type { Post } from "@/types";

// The profile timeline as a grid (plan 08, "Grid view"): one tile per post,
// its first photo or the start of its text; a tile opens the post.
const props = defineProps<{ posts: Post[] }>();
const { t } = useI18n();

const isPhoto = (p: Post) => p.type !== "video" && p.type !== "reel" && (p.media_ids?.length ?? 0) > 0;
const coverIds = computed(() => props.posts.map((p) => (isPhoto(p) ? (p.media_ids?.[0] ?? "") : "")));
const urls = useMediaList(() => coverIds.value.filter(Boolean));
// useMediaList drops nothing, but only resolves the non-empty ids: map them back.
const urlFor = computed(() => {
  const map: Record<string, string | null> = {};
  coverIds.value.filter(Boolean).forEach((id, i) => (map[id] = urls.value[i] ?? null));
  return map;
});
const excerpt = (p: Post) => (p.body || "").trim().slice(0, 140);
const label = (p: Post) =>
  t("profileTools.posts.openPost", { text: excerpt(p) || (isPhoto(p) ? t("profileTools.posts.photoPost") : t("profileTools.posts.textOnly")) });
</script>

<template>
  <ul class="grid grid-cols-2 gap-2 sm:grid-cols-3" data-testid="profile-posts-grid">
    <li v-for="(p, i) in posts" :key="p.id">
      <RouterLink
        :to="`/posts/${p.id}`"
        class="card group relative block aspect-square overflow-hidden focus:outline-none focus-visible:ring-4 focus-visible:ring-brand-400"
        :aria-label="label(p)"
        data-testid="profile-posts-grid-item"
      >
        <img
          v-if="coverIds[i] && urlFor[coverIds[i]]"
          :src="urlFor[coverIds[i]] ?? undefined"
          alt=""
          class="h-full w-full object-cover transition group-hover:scale-105"
          loading="lazy"
        />
        <span v-else-if="coverIds[i]" class="skeleton block h-full w-full rounded-none" aria-hidden="true" />
        <span
          v-else
          class="flex h-full w-full items-center justify-center bg-gradient-to-br from-brand-600 via-brand-700 to-ink p-3 text-center text-sm font-semibold leading-snug text-white"
          dir="auto"
        >
          <span class="line-clamp-6">{{ excerpt(p) || t("profileTools.posts.textOnly") }}</span>
        </span>
        <span v-if="(p.media_ids?.length ?? 0) > 1 && isPhoto(p)" class="absolute end-2 top-2 rounded-full bg-gray-950/60 p-1 text-white" aria-hidden="true">
          <Images class="h-4 w-4" />
        </span>
        <span v-else-if="p.type === 'video'" class="absolute end-2 top-2 rounded-full bg-gray-950/60 p-1 text-white" aria-hidden="true">
          <Play class="h-4 w-4" />
        </span>
        <span v-else-if="p.type === 'reel'" class="absolute end-2 top-2 rounded-full bg-gray-950/60 p-1 text-white" aria-hidden="true">
          <Clapperboard class="h-4 w-4" />
        </span>
      </RouterLink>
    </li>
  </ul>
</template>
