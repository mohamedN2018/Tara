import { useI18n } from "vue-i18n";

/** vue-i18n splits keys on dots, so dotted backend keys are looked up with underscores. */
const slug = (key: string) => key.replace(/\./g, "_");

/** Translated names for capability keys, namespaces, roles and audit actions; raw value if unknown. */
export function useAdminLabels() {
  const { t, te } = useI18n();
  const label = (path: string, raw: string) => (te(path) ? t(path) : raw);
  return {
    capLabel: (key: string) => label(`admin.caps.${slug(key)}`, key),
    namespaceLabel: (ns: string) => label(`admin.namespaces.${ns}`, ns),
    roleLabel: (role: string) => label(`admin.roleNames.${role}`, role),
    actionLabel: (action: string) => label(`admin.audit.actions.${slug(action)}`, action),
    metricLabel: (metric: string) => label(`admin.monitor.metrics.${metric}`, metric),
  };
}
