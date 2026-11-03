// iPhone photos are HEIC/HEIF. Media accepts them for `kind=image` and converts
// them to JPEG on the server, so the file is uploaded as-is with its real MIME.
// Most browsers cannot draw HEIC, so the composer shows a placeholder for it.

const HEIC_RE = /\.(heic|heif)$/i;
/** For `<input type="file" accept>`: some pickers hide HEIC behind `image/*`. */
export const IMAGE_ACCEPT = "image/*,.heic,.heif";

export function isHeic(file: { name?: string; type?: string } | null | undefined): boolean {
  if (!file) return false;
  const type = (file.type || "").toLowerCase();
  return HEIC_RE.test(file.name || "") || type.includes("heic") || type.includes("heif");
}

/**
 * The MIME to sign and upload with (the PUT must send exactly the same): the
 * browser's own type, or one taken from a `.heic`/`.heif` name when it reports
 * none (Chrome and Firefox on Windows do).
 */
export function uploadMime(file: { name?: string; type?: string }): string {
  if (file.type) return file.type;
  const ext = HEIC_RE.exec(file.name || "")?.[1]?.toLowerCase();
  return ext ? `image/${ext}` : "application/octet-stream";
}
