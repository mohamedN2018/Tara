import { mediaService } from "@/services/media";

/**
 * Download one media file through the media service's short-lived signed URL
 * (`GET /media/{id}/download-url/`). The server decides who may: an asset the
 * viewer can't see is 404, a transcoded video has no original (404), one still
 * processing is 409; the caller shows those as an error.
 */
export async function downloadMedia(id: string, open: (url: string) => void = clickLink): Promise<void> {
  open(await mediaService.downloadUrl(id));
}

function clickLink(url: string): void {
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  a.rel = "noopener";
  a.target = "_blank";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
