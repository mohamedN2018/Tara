// iPhone photos are HEIC/HEIF, which most browsers cannot show and media does
// not accept. Convert them to JPEG in the browser before preview and upload
// (ported from QTech's utils/heic.js). heic2any is large, so it is a lazy chunk:
// only people who pick a HEIC file download it, and vite.config.ts keeps it out
// of the service-worker precache. Media's own MIME and signature checks remain
// the real control.

const HEIC_RE = /\.(heic|heif)$/i;
export const JPEG_QUALITY = 0.9;
/** For `<input type="file" accept>`: some pickers hide HEIC behind `image/*`. */
export const IMAGE_ACCEPT = "image/*,.heic,.heif";

export function isHeic(file: { name?: string; type?: string } | null | undefined): boolean {
  if (!file) return false;
  const type = (file.type || "").toLowerCase();
  return HEIC_RE.test(file.name || "") || type.includes("heic") || type.includes("heif");
}

/** The file itself, or a JPEG copy of a HEIC photo. Throws if conversion fails. */
export async function toUploadable(file: File): Promise<File> {
  if (!isHeic(file)) return file;
  const { default: heic2any } = await import("heic2any");
  const out = await heic2any({ blob: file, toType: "image/jpeg", quality: JPEG_QUALITY });
  const blob = Array.isArray(out) ? out[0] : out;
  const name = (file.name || "photo").replace(HEIC_RE, "") + ".jpg";
  return new File([blob], name, { type: "image/jpeg" });
}
