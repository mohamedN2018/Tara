/**
 * A small zxcvbn-like password score for the sign-up meter (plan 08, track 1D).
 *
 * It mirrors what identity enforces (Django's validators: at least 10
 * characters, not a common password, not all digits, not like the account's
 * own details) and adds a rough strength on top. The server stays the judge:
 * a "strong" score here can still be refused there.
 */

export type StrengthLevel = 0 | 1 | 2 | 3 | 4;

export interface PasswordStrength {
  score: StrengthLevel;
  /** i18n key under `register.strength.*` for the level. */
  label: "tooShort" | "weak" | "fair" | "good" | "strong";
  /** i18n keys under `register.strength.tips.*`, most useful first. */
  tips: Array<"length" | "common" | "numeric" | "personal" | "variety" | "repeat">;
  /** Would the server's validators accept it (as far as can be told here)? */
  acceptable: boolean;
}

export const MIN_PASSWORD_LENGTH = 10;

// The head of the common-password lists Django checks against, plus the
// brand, which people reach for on a sign-up page.
const COMMON = [
  "password",
  "passw0rd",
  "123456",
  "qwerty",
  "azerty",
  "letmein",
  "welcome",
  "iloveyou",
  "admin",
  "abc123",
  "monkey",
  "dragon",
  "football",
  "baseball",
  "sunshine",
  "princess",
  "superman",
  "trustno1",
  "tara",
];

const SEQUENCES = ["abcdefghijklmnopqrstuvwxyz", "qwertyuiop", "asdfghjkl", "zxcvbnm", "0123456789"];

const LABELS: PasswordStrength["label"][] = ["tooShort", "weak", "fair", "good", "strong"];

function hasSequence(lower: string, run = 4): boolean {
  for (const seq of SEQUENCES) {
    for (let i = 0; i + run <= seq.length; i++) {
      const piece = seq.slice(i, i + run);
      if (lower.includes(piece) || lower.includes([...piece].reverse().join(""))) return true;
    }
  }
  return false;
}

/** Pieces of the person's own details that a password shouldn't be built from. */
function personalPieces(inputs: readonly string[]): string[] {
  return inputs
    .flatMap((value) => value.toLowerCase().split(/[@._\-\s]+/))
    .filter((piece) => piece.length >= 3);
}

export function passwordStrength(password: string, userInputs: readonly string[] = []): PasswordStrength {
  const tips: PasswordStrength["tips"] = [];
  const lower = password.toLowerCase();
  const length = [...password].length;

  const numeric = /^\d+$/.test(password);
  const common = COMMON.some((word) => lower.includes(word)) || hasSequence(lower);
  const personal = personalPieces(userInputs).some((piece) => lower.includes(piece));
  const repeated = /(.)\1{2,}/u.test(password);
  const classes = [/\p{Ll}/u, /\p{Lu}/u, /\d/, /[^\p{L}\d]/u].filter((re) => re.test(password)).length;
  // Letters in scripts without case (Arabic) count as their own class.
  const uncased = /\p{Lo}/u.test(password) ? 1 : 0;

  if (length < MIN_PASSWORD_LENGTH) tips.push("length");
  if (numeric) tips.push("numeric");
  if (common) tips.push("common");
  if (personal) tips.push("personal");
  if (repeated) tips.push("repeat");
  if (classes + uncased < 3) tips.push("variety");

  if (!password) return { score: 0, label: "tooShort", tips: [], acceptable: false };
  if (length < MIN_PASSWORD_LENGTH || numeric) {
    return { score: 0, label: "tooShort", tips, acceptable: false };
  }

  let points = classes + uncased;
  if (length >= 12) points += 1;
  if (length >= 16) points += 1;
  if (repeated) points -= 1;
  let score = Math.max(1, Math.min(4, points - 1)) as StrengthLevel;
  if (common || personal) score = 1;

  return { score, label: LABELS[score], tips, acceptable: !common && !personal };
}
