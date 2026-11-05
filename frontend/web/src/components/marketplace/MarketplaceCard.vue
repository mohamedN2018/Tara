<script setup lang="ts">
import { Bookmark, MapPin, Scale } from "lucide-vue-next";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import UserAvatar from "@/components/common/UserAvatar.vue";
import { categoryGradient, categoryIcon } from "@/lib/listing";
import { useMediaUrl } from "@/lib/useMediaUrl";
import { marketplaceService } from "@/services/marketplace";
import { useAuthStore } from "@/stores/auth";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";
import type { Listing } from "@/types";

import ListingOwnerMenu from "./ListingOwnerMenu.vue";
import PriceTag from "./PriceTag.vue";
import { categoryLabel } from "./useCategories";
import { useCompare } from "./useCompare";

// `manage`: the seller's own grid (Selling): the "..." menu replaces save/compare.
const props = withDefaults(defineProps<{ listing: Listing; manage?: boolean }>(), { manage: false });
const emit = defineEmits<{ unsaved: [id: string]; updated: [listing: Listing]; edit: [listing: Listing] }>();
const { t, te } = useI18n();
const auth = useAuthStore();
const directory = useDirectoryStore();
const toasts = useToastStore();
const compare = useCompare();

const cover = useMediaUrl(() => props.listing.media?.[0]?.media_id);
const gradient = computed(() => categoryGradient(props.listing.category?.slug));
const icon = computed(() => categoryIcon(props.listing.category?.slug));
const conditionLabel = computed(() => t(`market.conditions.${props.listing.condition}`));
const own = computed(() => auth.account?.id === props.listing.seller_id);
// Reserved and sold say so; drafts and pending ones (own listings) show their status.
const badge = computed(() => {
  const a = props.listing.availability;
  if (a === "reserved" || a === "sold") return t(`market.availability.${a}`);
  if (props.listing.status !== "active") return t(`market.statuses.${props.listing.status}`);
  return "";
});

const saved = ref(!!props.listing.is_saved);
watch(() => props.listing.is_saved, (v) => (saved.value = !!v));
const inCompare = computed(() => compare.has(props.listing.id));

async function toggleSave() {
  const next = !saved.value;
  saved.value = next;
  try {
    if (next) await marketplaceService.save(props.listing.id);
    else {
      await marketplaceService.unsave(props.listing.id);
      emit("unsaved", props.listing.id);
    }
  } catch (e) {
    saved.value = !next;
    toasts.error(e);
  }
}

function toggleCompare() {
  if (!compare.toggle(props.listing.id)) toasts.error(t("market.compare.full"));
}
</script>

<template>
  <!-- A managed card never lifts on hover: the lift would trap its "..." menu under the next row. -->
  <article
    class="card flex flex-col"
    :class="manage && own ? 'relative focus-within:z-20' : 'card-hover'"
    data-testid="listing-card"
  >
    <RouterLink :to="`/marketplace/${listing.id}`" class="block">
      <div class="relative aspect-square overflow-hidden rounded-t-2xl">
        <img v-if="cover" :src="cover" class="h-full w-full object-cover" loading="lazy" :alt="listing.title" />
        <div
          v-else
          class="flex h-full flex-col items-center justify-center gap-2 bg-gradient-to-br text-gray-500 dark:text-gray-300"
          :class="gradient"
        >
          <component :is="icon" class="h-10 w-10 opacity-70" />
          <span v-if="listing.category" class="text-xs font-medium opacity-80">{{ categoryLabel(listing.category, t, te) }}</span>
        </div>

        <span
          class="absolute top-2 start-2 rounded-full bg-white/90 px-2 py-0.5 text-[11px] font-semibold text-gray-700 shadow-sm dark:bg-gray-900/80 dark:text-gray-200"
        >
          {{ conditionLabel }}
        </span>
        <span
          v-if="badge"
          class="absolute top-2 end-2 rounded-full bg-gray-900/80 px-2 py-0.5 text-[11px] font-semibold text-white"
        >
          {{ badge }}
        </span>
      </div>

      <div class="p-3 pb-2">
        <PriceTag :listing="listing" />
        <h3 class="truncate text-start text-sm font-medium"><bdi>{{ listing.title }}</bdi></h3>
        <p class="mt-1 flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
          <MapPin class="h-3 w-3 shrink-0" aria-hidden="true" />
          <span class="truncate text-start"><bdi>{{ listing.location || "—" }}</bdi></span>
        </p>
      </div>
    </RouterLink>

    <div v-if="manage && own" class="mt-auto flex items-center gap-2 px-3 pb-3 text-xs text-gray-500 dark:text-gray-400">
      <span class="min-w-0 flex-1 truncate">
        {{ t("market.views", listing.view_count ?? 0) }} · {{ t("market.saves", listing.save_count ?? 0) }}
      </span>
      <ListingOwnerMenu :listing="listing" @updated="emit('updated', $event)" @edit="emit('edit', listing)" />
    </div>
    <div v-else class="mt-auto flex items-center gap-1 px-3 pb-3">
      <RouterLink
        :to="{ name: 'marketplace-seller', params: { id: listing.seller_id } }"
        class="flex min-w-0 flex-1 items-center gap-1.5 text-xs text-gray-500 hover:text-brand-600 dark:text-gray-400"
        :title="t('market.viewSeller')"
      >
        <UserAvatar :name="directory.label(listing.seller_id)" :media-id="directory.avatarOf(listing.seller_id)" :size="20" />
        <span class="truncate text-start"><bdi>{{ directory.label(listing.seller_id) }}</bdi></span>
      </RouterLink>
      <button
        type="button"
        class="rounded-full p-1.5 transition hover:bg-gray-100 dark:hover:bg-gray-800"
        :class="inCompare ? 'text-brand-600 dark:text-brand-300' : 'text-gray-400'"
        :aria-pressed="inCompare"
        :aria-label="inCompare ? t('market.compare.remove') : t('market.compare.add')"
        :title="inCompare ? t('market.compare.remove') : t('market.compare.add')"
        @click="toggleCompare"
      >
        <Scale class="h-4 w-4" />
      </button>
      <button
        v-if="!own"
        type="button"
        class="rounded-full p-1.5 transition hover:bg-gray-100 dark:hover:bg-gray-800"
        :class="saved ? 'text-brand-600 dark:text-brand-300' : 'text-gray-400'"
        :aria-pressed="saved"
        :aria-label="saved ? t('market.unsave') : t('market.save')"
        :title="saved ? t('market.unsave') : t('market.save')"
        @click="toggleSave"
      >
        <Bookmark class="h-4 w-4" :fill="saved ? 'currentColor' : 'none'" />
      </button>
    </div>
  </article>
</template>
