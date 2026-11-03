<script setup lang="ts">
import { PenSquare, Plus, Store } from "lucide-vue-next";
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { useEscapeKey } from "@/lib/useEscapeKey";

const { t } = useI18n();
const router = useRouter();

const open = ref(false);
useEscapeKey(open, () => (open.value = false));

function newPost() {
  open.value = false;
  router.push("/home");
}
function newListing() {
  open.value = false;
  router.push({ path: "/marketplace", query: { create: "1" } });
}
</script>

<template>
  <div class="relative">
    <button
      class="icon-btn"
      :class="open ? 'bg-brand-50 text-brand-600 dark:bg-brand-950/40 dark:text-brand-300' : ''"
      :aria-label="t('nav.create')"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click="open = !open"
    >
      <Plus class="h-5 w-5" />
    </button>

    <template v-if="open">
      <div class="fixed inset-0 z-40" @click="open = false" />
      <div class="popover absolute end-0 z-50 mt-2 w-56 p-1.5" role="menu">
        <h3 class="px-2 pb-1 text-sm font-bold">{{ t("create.menu") }}</h3>
        <button
          class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
          role="menuitem"
          @click="newPost"
        >
          <span class="flex h-9 w-9 items-center justify-center rounded-full bg-brand-50 text-brand-600 dark:bg-brand-950/40 dark:text-brand-300">
            <PenSquare class="h-4 w-4" />
          </span>
          {{ t("create.post") }}
        </button>
        <button
          class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-start text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800"
          role="menuitem"
          @click="newListing"
        >
          <span class="flex h-9 w-9 items-center justify-center rounded-full bg-brand-50 text-brand-600 dark:bg-brand-950/40 dark:text-brand-300">
            <Store class="h-4 w-4" />
          </span>
          {{ t("create.listing") }}
        </button>
      </div>
    </template>
  </div>
</template>
