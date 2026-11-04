<script setup lang="ts">
// Sign-up's strength meter (plan 08, track 1D). The scoring lives in
// lib/passwordStrength.ts; identity's validators still decide.
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { passwordStrength } from "@/lib/passwordStrength";

const props = withDefaults(defineProps<{ password: string; userInputs?: string[]; id?: string }>(), {
  userInputs: () => [],
  id: "password-strength",
});

const { t } = useI18n();
const strength = computed(() => passwordStrength(props.password, props.userInputs));

// Brand ramp, weakest to strongest: Accent Pink, Neon Violet, Tara Purple, the gradient.
const FILL = ["bg-accent-500/60", "bg-accent-500", "bg-brand-400", "bg-brand-600", "bg-tara-gradient"];
const fill = computed(() => FILL[strength.value.score]);
// "Too short" still lights one bar, faded, so the meter visibly reacts.
const filled = computed(() => Math.max(strength.value.score, 1));
const tip = computed(() => strength.value.tips[0]);
</script>

<template>
  <div v-if="password" :id="id" class="mt-2" data-testid="password-strength" :data-score="strength.score">
    <div class="flex gap-1" aria-hidden="true">
      <span
        v-for="bar in 4"
        :key="bar"
        class="h-1.5 flex-1 rounded-full transition-colors duration-200"
        :class="bar <= filled ? fill : 'bg-gray-200 dark:bg-gray-800'"
      />
    </div>
    <p class="mt-1 text-xs text-gray-600 dark:text-gray-300" aria-live="polite">
      <span class="font-semibold">{{ t("register.strength.label", { level: t(`register.strength.${strength.label}`) }) }}</span>
      <span v-if="tip"> · {{ t(`register.strength.tips.${tip}`) }}</span>
    </p>
  </div>
</template>
