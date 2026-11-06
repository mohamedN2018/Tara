<script setup lang="ts">
// /welcome/topics (Tara Intelligence WP 6.6): shown once after sign-up, only while the
// server says the account has not onboarded (`onboarded_at` null). Otherwise, or when
// this server has no onboarding yet, it goes straight on.
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import OnboardingTopics from "@/components/feed/OnboardingTopics.vue";
import { topicsPicked } from "@/lib/onboarding";
import { safeRedirect } from "@/lib/redirect";
import { feedService } from "@/services/feed";

const route = useRoute();
const router = useRouter();
const show = ref(false);
const next = () => safeRedirect(route.query.next);

function leave() {
  topicsPicked();
  void router.replace(next());
}

onMounted(async () => {
  try {
    const prefs = await feedService.preferences();
    // `onboarded_at` absent: a server without onboarding; set: already done.
    if (!("onboarded_at" in prefs) || prefs.onboarded_at) return leave();
    show.value = true;
  } catch {
    leave();
  }
});
</script>

<template>
  <main class="min-h-screen bg-gray-50 px-4 py-8 dark:bg-gray-950 sm:py-14">
    <div class="mx-auto w-full max-w-[640px]">
      <OnboardingTopics v-if="show" @done="leave" />
    </div>
  </main>
</template>
