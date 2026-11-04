<script setup lang="ts">
// The seller's "..." menu for one of their listings (Selling cards and the
// listing page): edit, publish a draft, reserve / reactivate, mark sold and
// archive. Every item is a real marketplace call; the server decides again.
import { Archive, BadgeCheck, Clock, MoreHorizontal, Pencil, RotateCcw, Send } from "lucide-vue-next";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import ConfirmActionDialog from "@/components/social/ConfirmActionDialog.vue";
import { useEscapeKey } from "@/lib/useEscapeKey";
import { type ListingAction, marketplaceService } from "@/services/marketplace";
import { useToastStore } from "@/stores/toasts";
import type { Listing } from "@/types";

const props = withDefaults(defineProps<{ listing: Listing; buttonClass?: string }>(), {
  buttonClass: "rounded-full p-1.5 text-gray-500 transition hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800",
});
const emit = defineEmits<{ updated: [listing: Listing]; edit: [] }>();

const { t } = useI18n();
const toasts = useToastStore();
const open = ref(false);
const confirming = ref(false);
const busy = ref(false);
useEscapeKey(open, () => (open.value = false));

const status = computed(() => props.listing.status);
const canEdit = computed(() => status.value !== "removed");
// Archive is allowed from these (services.py transitions).
const canArchive = computed(() => ["draft", "active", "reserved", "rejected"].includes(status.value));

const DONE: Record<ListingAction, string> = {
  reserve: "commerce.listing.reserved",
  reactivate: "commerce.listing.reactivated",
  mark_sold: "commerce.listing.sold",
  archive: "commerce.listing.archived",
};

async function run(action: ListingAction) {
  open.value = false;
  if (busy.value) return;
  busy.value = true;
  try {
    const next = await marketplaceService.transition(props.listing.id, action);
    emit("updated", { ...props.listing, ...next });
    toasts.success(t(DONE[action]));
    confirming.value = false;
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

async function publish() {
  open.value = false;
  if (busy.value) return;
  busy.value = true;
  try {
    const next = await marketplaceService.publish(props.listing.id);
    emit("updated", { ...props.listing, ...next });
    toasts.success(next.status === "active" ? t("market.posted") : t("market.pendingReview"));
  } catch (e) {
    toasts.error(e);
  } finally {
    busy.value = false;
  }
}

function edit() {
  open.value = false;
  emit("edit");
}

const item =
  "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 disabled:opacity-60 dark:hover:bg-gray-800";
</script>

<template>
  <!-- A removed listing has nothing left to manage, so no empty menu. -->
  <div v-if="canEdit || canArchive" class="relative">
    <button
      type="button"
      :class="buttonClass"
      :aria-label="t('commerce.listing.manage', { title: listing.title })"
      aria-haspopup="menu"
      :aria-expanded="open"
      :disabled="busy"
      data-testid="listing-owner-menu"
      @click.prevent="open = !open"
    >
      <MoreHorizontal class="h-5 w-5" aria-hidden="true" />
    </button>
    <template v-if="open">
      <div class="fixed inset-0 z-40" @click="open = false" />
      <div class="popover absolute end-0 top-full z-50 mt-1 w-60 p-1.5" role="menu" data-testid="listing-owner-items">
        <button v-if="canEdit" role="menuitem" :class="item" @click="edit">
          <Pencil class="h-4 w-4" aria-hidden="true" />
          {{ status === "rejected" ? t("commerce.listing.editResubmit") : t("commerce.listing.edit") }}
        </button>
        <button v-if="status === 'draft'" role="menuitem" :class="item" @click="publish">
          <Send class="h-4 w-4 rtl:-scale-x-100" aria-hidden="true" /> {{ t("market.publish") }}
        </button>
        <button v-if="status === 'active'" role="menuitem" :class="item" @click="run('reserve')">
          <Clock class="h-4 w-4" aria-hidden="true" /> {{ t("market.reserve") }}
        </button>
        <button v-if="status === 'reserved'" role="menuitem" :class="item" @click="run('reactivate')">
          <RotateCcw class="h-4 w-4" aria-hidden="true" /> {{ t("market.reactivate") }}
        </button>
        <button v-if="status === 'active' || status === 'reserved'" role="menuitem" :class="item" @click="run('mark_sold')">
          <BadgeCheck class="h-4 w-4" aria-hidden="true" /> {{ t("market.markSold") }}
        </button>
        <template v-if="canArchive">
          <div class="my-1 border-t border-gray-100 dark:border-gray-800" />
          <button role="menuitem" :class="item" class="text-red-600 dark:text-red-400" @click="open = false; confirming = true">
            <Archive class="h-4 w-4" aria-hidden="true" /> {{ t("commerce.listing.archive") }}
          </button>
        </template>
      </div>
    </template>
    <ConfirmActionDialog
      v-if="confirming"
      :title="t('commerce.listing.archiveTitle')"
      :hint="t('commerce.listing.archiveHint')"
      :confirm-label="t('commerce.listing.archive')"
      :busy="busy"
      @confirm="run('archive')"
      @cancel="confirming = false"
    />
  </div>
</template>
