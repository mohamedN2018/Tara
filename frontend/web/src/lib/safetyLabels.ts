// Labels for moderation values shown in the console and the Support inbox.
// A stored report reason is a reason code, optionally followed by ": " and the
// reporter's own words; services that take free text store just the text.
import { useI18n } from "vue-i18n";

import { reasonCode } from "@/services/moderation";

export function useSafetyLabels() {
  const { t, te } = useI18n();
  const known = (code: string) => !!code && /^[a-z_]+$/.test(code) && te(`safety.reasons.${code}`);
  return {
    targetLabel: (type: string) => (te(`safety.targets.${type}`) ? t(`safety.targets.${type}`) : type),
    /** The chosen reason's name; "In their words" when the reason is free text. */
    reasonLabel: (reason: string) => {
      const code = reasonCode(reason);
      if (!reason) return t("safety.reasons.none");
      return known(code) ? t(`safety.reasons.${code}`) : t("safety.reasons.custom");
    },
    /** The reporter's own words, if any. */
    reasonDetail: (reason: string) => {
      const code = reasonCode(reason);
      if (!reason) return "";
      if (!known(code)) return reason;
      return reason.slice(code.length).replace(/^:\s*/, "");
    },
    decisionLabel: (decision: string) => (te(`safety.decisions.${decision}`) ? t(`safety.decisions.${decision}`) : decision),
    stateLabel: (state: string) => (te(`safety.states.${state}`) ? t(`safety.states.${state}`) : state),
  };
}
