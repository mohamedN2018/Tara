import { defineStore } from "pinia";
import { ref } from "vue";

import { i18n } from "@/i18n";
import { type Page, pageService } from "@/services/pages";

// Page id -> name, handle and avatar, for posts published as a page (their
// author_id is the page id). Unknown ids are fetched in debounced batches of 50
// through GET /pages/?ids=; pages the viewer may not see come back missing and
// read as a neutral label. In memory only: page names change and are cheap.
interface Entry {
  name: string;
  handle: string;
  avatar: string | null;
}

const BATCH_SIZE = 50;
const DEBOUNCE_MS = 40;

export const usePageDirectoryStore = defineStore("pageDirectory", () => {
  const entries = ref<Record<string, Entry>>({});
  const unavailable = ref<Record<string, true>>({});
  const queued = new Set<string>();
  const inflight = new Set<string>();
  let timer: number | null = null;

  function remember(page: Pick<Page, "id" | "name" | "handle" | "avatar_media_id">) {
    entries.value[page.id] = { name: page.name, handle: page.handle, avatar: page.avatar_media_id };
    delete unavailable.value[page.id];
  }

  async function lookup(ids: string[]) {
    ids.forEach((id) => inflight.add(id));
    try {
      const pages = await pageService.byIds(ids);
      pages.forEach(remember);
      const found = new Set(pages.map((p) => p.id));
      for (const id of ids) if (!found.has(id)) unavailable.value[id] = true;
    } catch {
      // Profile down: try again on the next read.
    } finally {
      ids.forEach((id) => inflight.delete(id));
    }
  }

  function flush() {
    timer = null;
    const ids = [...queued];
    queued.clear();
    for (let i = 0; i < ids.length; i += BATCH_SIZE) void lookup(ids.slice(i, i + BATCH_SIZE));
  }

  function request(id: string) {
    if (entries.value[id] || unavailable.value[id] || queued.has(id) || inflight.has(id)) return;
    queued.add(id);
    if (timer === null) timer = window.setTimeout(flush, DEBOUNCE_MS);
  }

  function label(id?: string | null): string {
    if (!id) return "";
    request(id);
    return entries.value[id]?.name || (unavailable.value[id] ? i18n.global.t("profile.unknownUser") : "…");
  }
  function avatarOf(id?: string | null): string | null {
    if (!id) return null;
    request(id);
    return entries.value[id]?.avatar ?? null;
  }

  return { entries, remember, label, avatarOf };
});
