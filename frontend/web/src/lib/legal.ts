/**
 * Versions of Tara's legal documents. Registration records consent against
 * these strings (`terms_version`), so a new text means a new version here.
 *
 * Both are drafts pending legal review (owner decision 5.14); `LEGAL_IS_DRAFT`
 * keeps the banner on the legal pages until the reviewed text replaces them.
 */
export const TERMS_VERSION = "2026-11-04-draft";
export const PRIVACY_VERSION = "2026-11-04-draft";
export const LEGAL_IS_DRAFT = true;

export type LegalDocKind = "terms" | "privacy";

export const LEGAL_DOCS: readonly LegalDocKind[] = ["terms", "privacy"];

export const LEGAL_VERSIONS: Readonly<Record<LegalDocKind, string>> = {
  terms: TERMS_VERSION,
  privacy: PRIVACY_VERSION,
};

/** The public path of a legal document. */
export const legalPath = (kind: LegalDocKind) => `/legal/${kind}`;

export function isLegalDoc(value: unknown): value is LegalDocKind {
  return typeof value === "string" && (LEGAL_DOCS as readonly string[]).includes(value);
}
