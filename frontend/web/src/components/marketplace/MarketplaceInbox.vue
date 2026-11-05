<script setup lang="ts">
// The marketplace inbox: one row per inquiry. "Selling": buyers who asked
// about my listings; "Buying": listings I asked about. The conversation itself
// lives in Messages, so "Message" opens the listing's marketplace thread.
import { MessageCircle } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import UserAvatar from "@/components/common/UserAvatar.vue";
import EmptyState from "@/components/states/EmptyState.vue";
import ErrorState from "@/components/states/ErrorState.vue";
import LoadingSkeleton from "@/components/states/LoadingSkeleton.vue";
import { relativeTime } from "@/lib/format";
import { chatService } from "@/services/chat";
import { type InquiryRole, type InquiryRow, marketplaceService } from "@/services/marketplace";
import { useDirectoryStore } from "@/stores/directory";
import { useToastStore } from "@/stores/toasts";
import type { Listing } from "@/types";

import ListingThumb from "./ListingThumb.vue";
import PriceTag from "./PriceTag.vue";

// `switchable=false` pins the role (Buying's "Messaged sellers" list).
const props = withDefaults(defineProps<{ role?: InquiryRole; switchable?: boolean }>(), {
  role: "seller",
  switchable: true,
});

const { t } = useI18n();
const router = useRouter();
const directory = useDirectoryStore();
const toasts = useToastStore();

const role = ref<InquiryRole>(props.role);
const rows = ref<InquiryRow[]>([]);
const cursor = ref<string | null>(null);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref(false);
const opening = ref("");

async function load() {
  loading.value = true;
  error.value = false;
  try {
    const page = await marketplaceService.inquiries(role.value);
    rows.value = page.data;
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch {
    error.value = true;
  } finally {
    loading.value = false;
  }
}

async function loadMore() {
  if (!hasMore.value || loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await marketplaceService.inquiries(role.value, cursor.value ?? undefined);
    rows.value.push(...page.data);
    cursor.value = page.page.next_cursor;
    hasMore.value = page.page.has_more;
  } catch (e) {
    toasts.error(e);
  } finally {
    loadingMore.value = false;
  }
}

async function message(row: InquiryRow) {
  if (opening.value) return;
  opening.value = row.id;
  try {
    // The listing's marketplace thread (never a plain DM: one thread per listing).
    const conversation = await chatService.listingThread(row.listing_id, row.counterpart_id, 3000);
    router.push(conversation ? { name: "messages", params: { id: conversation.id }, query: { folder: "marketplace" } } : { path: "/messages", query: { folder: "marketplace" } });
  } catch (e) {
    toasts.error(e);
  } finally {
    opening.value = "";
  }
}

// ListingThumb reads a listing's cover and category; a row carries just those.
const thumbOf = (row: InquiryRow) =>
  ({
    media: row.listing?.cover_media_id ? [{ media_id: row.listing.cover_media_id, position: 0 }] : [],
    category: { slug: row.listing?.category_slug ?? "" },
  }) as unknown as Listing;

function setRole(next: InquiryRole) {
  if (role.value === next) return;
  role.value = next;
  load();
}

onMounted(load);
watch(() => props.role, (r) => setRole(r));
</script>

<template>
  <section class="card p-4" data-testid="market-inbox">
    <div v-if="switchable" class="mb-3 flex gap-1 rounded-xl bg-gray-100 p-1 text-sm dark:bg-gray-800" role="tablist" :aria-label="t('commerce.inbox.title')">
      <button
        v-for="r in (['seller', 'buyer'] as const)"
        :key="r"
        role="tab"
        :aria-selected="role === r"
        class="flex-1 rounded-lg py-1.5 font-medium transition"
        :class="role === r ? 'bg-white text-brand-600 shadow-sm dark:bg-gray-900 dark:text-brand-300' : 'text-gray-500 dark:text-gray-400'"
        :data-testid="`inbox-role-${r}`"
        @click="setRole(r)"
      >
        {{ r === "seller" ? t("commerce.inbox.selling") : t("commerce.inbox.buying") }}
      </button>
    </div>

    <LoadingSkeleton v-if="loading" :rows="3" />
    <ErrorState v-else-if="error" @retry="load" />
    <EmptyState v-else-if="!rows.length">
      {{ role === "seller" ? t("commerce.inbox.emptySelling") : t("commerce.inbox.emptyBuying") }}
    </EmptyState>
    <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800">
      <li v-for="row in rows" :key="row.id" class="flex items-center gap-3 py-3" data-testid="inquiry-row">
        <RouterLink
          v-if="row.listing"
          :to="`/marketplace/${row.listing_id}`"
          class="w-14 shrink-0"
          :aria-label="row.listing.title"
        >
          <ListingThumb :listing="thumbOf(row)" />
        </RouterLink>
        <div v-else class="w-14 shrink-0"><ListingThumb :listing="thumbOf(row)" /></div>

        <div class="min-w-0 flex-1">
          <p class="flex items-center gap-2 text-sm">
            <UserAvatar :name="directory.label(row.counterpart_id)" :media-id="directory.avatarOf(row.counterpart_id)" :size="20" />
            <span class="truncate text-start font-semibold"><bdi>{{ directory.label(row.counterpart_id) }}</bdi></span>
            <span class="shrink-0 text-xs text-gray-500 dark:text-gray-400">· {{ relativeTime(row.last_activity_at) }}</span>
          </p>
          <p v-if="row.listing" class="truncate text-start text-sm">
            <RouterLink :to="`/marketplace/${row.listing_id}`" class="hover:underline"><bdi>{{ row.listing.title }}</bdi></RouterLink>
          </p>
          <p v-else class="text-sm text-gray-500 dark:text-gray-400">{{ t("commerce.inbox.gone") }}</p>
          <div class="flex flex-wrap items-center gap-x-2 text-xs text-gray-500 dark:text-gray-400">
            <PriceTag v-if="row.listing" :listing="row.listing" class="!text-xs" />
            <span v-if="row.listing && row.listing.availability && row.listing.availability !== 'available'">
              · {{ t(`market.availability.${row.listing.availability}`) }}
            </span>
          </div>
          <p v-if="row.first_message" class="mt-0.5 truncate text-xs text-gray-600 dark:text-gray-300" dir="auto">
            “{{ row.first_message }}”
          </p>
        </div>

        <button
          type="button"
          class="btn-ghost shrink-0 px-3 text-sm"
          :disabled="opening === row.id"
          :aria-label="t('commerce.inbox.messageNamed', { name: directory.label(row.counterpart_id) })"
          @click="message(row)"
        >
          <MessageCircle class="h-4 w-4" aria-hidden="true" />
          <span class="hidden sm:inline">{{ t("commerce.inbox.message") }}</span>
        </button>
      </li>
    </ul>
    <div v-if="hasMore" class="mt-3 flex justify-center">
      <button class="btn-ghost" :disabled="loadingMore" @click="loadMore">
        {{ loadingMore ? t("states.loading") : t("feed.loadMore") }}
      </button>
    </div>
  </section>
</template>
