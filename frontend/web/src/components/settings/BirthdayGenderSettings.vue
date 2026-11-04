<script setup lang="ts">
// Birthday and gender, and who sees them (PATCH /me/). Identity enforces the
// audience on GET /me/people/<id>/personal/; the date of birth itself is read
// only here because it drives the age rules.
import { computed, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";

import { identityService } from "@/services/identity";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";
import type { Account } from "@/types";

type Audience = NonNullable<Account["birthday_visibility"]>;
type Gender = NonNullable<Account["gender"]>;

const { t, locale } = useI18n();
const auth = useAuthStore();
const toasts = useToastStore();
const uid = useId();

const AUDIENCES: Audience[] = ["friends", "only_me"];
const GENDERS: Gender[] = ["female", "male", "custom", "prefer_not_to_say"];

const form = ref({
  gender: "" as Gender,
  gender_custom: "",
  birthday_visibility: "only_me" as Audience,
  gender_visibility: "only_me" as Audience,
});
function fill(a: Account | null) {
  form.value = {
    gender: a?.gender ?? "",
    gender_custom: a?.gender_custom ?? "",
    birthday_visibility: a?.birthday_visibility ?? "only_me",
    gender_visibility: a?.gender_visibility ?? "only_me",
  };
}
watch(() => auth.account, fill, { immediate: true });

const saving = ref(false);

const birthday = computed(() => {
  const dob = auth.account?.date_of_birth;
  if (!dob) return "";
  // Day and month: the year is never shown to anyone, the owner sees it here.
  return new Intl.DateTimeFormat(locale.value, { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(
    new Date(`${dob}T00:00:00Z`),
  );
});

const dirty = computed(() => {
  const a = auth.account;
  if (!a) return false;
  const f = form.value;
  return (
    f.gender !== (a.gender ?? "") ||
    (f.gender === "custom" && f.gender_custom.trim() !== (a.gender_custom ?? "")) ||
    f.birthday_visibility !== (a.birthday_visibility ?? "only_me") ||
    f.gender_visibility !== (a.gender_visibility ?? "only_me")
  );
});

async function save() {
  if (saving.value || !dirty.value) return;
  saving.value = true;
  try {
    const f = form.value;
    auth.account = await identityService.updateAccount({
      gender: f.gender,
      gender_custom: f.gender === "custom" ? f.gender_custom.trim() : "",
      birthday_visibility: f.birthday_visibility,
      gender_visibility: f.gender_visibility,
    });
    toasts.success(t("settingsCenter.personal.saved"));
  } catch (e) {
    toasts.error(e);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section id="personal" class="card mb-4 scroll-mt-20 p-4" data-testid="birthday-gender">
    <h2 class="font-semibold">{{ t("settingsCenter.personal.title") }}</h2>
    <p class="mb-3 mt-1 text-sm text-gray-600 dark:text-gray-300">{{ t("settingsCenter.personal.lead") }}</p>

    <form class="space-y-4" @submit.prevent="save">
      <div class="grid gap-3 sm:grid-cols-2">
        <div>
          <span class="label">{{ t("settingsCenter.personal.birthday") }}</span>
          <p class="rounded-xl bg-gray-50 px-3 py-2 text-sm dark:bg-gray-800/60">{{ birthday || t("settingsCenter.personal.noBirthday") }}</p>
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t("settingsCenter.personal.birthdayHint") }}</p>
        </div>
        <div>
          <label :for="`${uid}-bday-aud`" class="label">{{ t("settingsCenter.personal.audience") }}</label>
          <select :id="`${uid}-bday-aud`" v-model="form.birthday_visibility" class="input" data-testid="birthday-visibility">
            <option v-for="a in AUDIENCES" :key="a" :value="a">{{ t(`settingsCenter.personal.audiences.${a}`) }}</option>
          </select>
        </div>
      </div>

      <div class="grid gap-3 sm:grid-cols-2">
        <div>
          <label :for="`${uid}-gender`" class="label">{{ t("settingsCenter.personal.gender") }}</label>
          <select :id="`${uid}-gender`" v-model="form.gender" class="input" data-testid="gender-select">
            <option value="">{{ t("settingsCenter.personal.genders.none") }}</option>
            <option v-for="g in GENDERS" :key="g" :value="g">{{ t(`settingsCenter.personal.genders.${g}`) }}</option>
          </select>
        </div>
        <div>
          <label :for="`${uid}-gender-aud`" class="label">{{ t("settingsCenter.personal.audience") }}</label>
          <select :id="`${uid}-gender-aud`" v-model="form.gender_visibility" class="input" data-testid="gender-visibility">
            <option v-for="a in AUDIENCES" :key="a" :value="a">{{ t(`settingsCenter.personal.audiences.${a}`) }}</option>
          </select>
        </div>
      </div>
      <div v-if="form.gender === 'custom'">
        <label :for="`${uid}-gender-custom`" class="label">{{ t("settingsCenter.personal.genderCustom") }}</label>
        <input :id="`${uid}-gender-custom`" v-model="form.gender_custom" class="input" dir="auto" maxlength="40" required />
      </div>

      <button type="submit" class="btn-primary" :disabled="saving || !dirty" data-testid="birthday-gender-save">
        {{ t("settingsCenter.personal.save") }}
      </button>
    </form>
  </section>
</template>
