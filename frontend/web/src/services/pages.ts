import { api } from "@/lib/api";
import type { CursorPage, Post } from "@/types";

/** Contact keys the profile service accepts (links must be http(s)). */
export const PAGE_LINK_KEYS = ["website", "instagram", "x", "linkedin", "youtube", "tiktok"] as const;
export const PAGE_CONTACT_KEYS = ["email", "phone", "whatsapp", ...PAGE_LINK_KEYS] as const;
export type PageContactKey = (typeof PAGE_CONTACT_KEYS)[number];
export type PageContact = Partial<Record<PageContactKey | string, string>>;

export interface Page {
  id: string;
  handle: string;
  name: string;
  category: string;
  description: string;
  location: string;
  status: string;
  avatar_media_id: string | null;
  cover_media_id: string | null;
  contact: PageContact;
  owner_account_id: string;
  my_role: string | null;
  /** Null when graph could not answer: hide the count, never show a made-up 0. */
  viewer_following: boolean | null;
  followers_count: number | null;
  created_at: string;
}

export interface PageNameChange {
  old_name: string;
  new_name: string;
  changed_at: string;
}

export interface PageTransparency {
  page_id: string;
  name: string;
  category: string;
  created_at: string;
  name_changes: PageNameChange[];
}

export interface PageMember {
  id: string;
  account_id: string;
  role: string;
}

export interface PageCreate {
  handle: string;
  name: string;
  category?: string;
  description?: string;
  location?: string;
  contact?: PageContact;
  avatar_media_id?: string | null;
  cover_media_id?: string | null;
}

export type PageUpdate = Partial<
  Pick<Page, "name" | "category" | "description" | "location" | "status" | "contact" | "avatar_media_id" | "cover_media_id">
>;

export const PAGE_ROLES = ["admin", "editor", "moderator", "advertiser", "analyst"];
/** Page handles the server refuses (they are routes of the Pages manager). */
export const RESERVED_PAGE_HANDLES = ["id", "manage", "new", "create", "mine", "followed", "discover", "settings", "tara"];
export const PAGE_HANDLE_RE = /^[a-zA-Z0-9_]{3,30}$/;

/** The roles that may post as the page, edit it, or delete its posts (the server checks again). */
export const canPostAs = (p: Pick<Page, "my_role" | "status">) =>
  ["owner", "admin", "editor"].includes(p.my_role ?? "") && p.status === "published";
export const canEditPage = (p: Pick<Page, "my_role">) => ["owner", "admin", "editor"].includes(p.my_role ?? "");
export const canManagePage = (p: Pick<Page, "my_role">) => ["owner", "admin"].includes(p.my_role ?? "");
export const canModeratePosts = (p: Pick<Page, "my_role">) =>
  ["owner", "admin", "editor", "moderator"].includes(p.my_role ?? "");

/** The `href` for a contact value: links as given (http(s) only), tel:, mailto: and wa.me. */
export function contactHref(key: string, value: string): string | null {
  const v = value.trim();
  if (!v) return null;
  if (key === "email") return `mailto:${v}`;
  if (key === "phone") return `tel:${v.replace(/[^\d+]/g, "")}`;
  if (key === "whatsapp") return `https://wa.me/${v.replace(/\D/g, "")}`;
  return /^https?:\/\//i.test(v) ? v : null;
}

/** Contact values without blanks (the server drops them too). */
export function cleanContact(contact: PageContact): PageContact {
  return Object.fromEntries(Object.entries(contact).filter(([, v]) => (v ?? "").trim())) as PageContact;
}

/** The contact keys a validation error names (``contact.website`` or ``website``). */
export function invalidContactKeys(details: { field: string | null }[] | undefined): string[] {
  const keys = new Set<string>();
  for (const d of details ?? []) {
    const parts = (d.field ?? "").split(".");
    for (const p of parts) if ((PAGE_CONTACT_KEYS as readonly string[]).includes(p)) keys.add(p);
  }
  return [...keys];
}

/** `ok`, `invalid` or `reserved`: checked before the server is asked. */
export function validatePageHandle(handle: string): "ok" | "invalid" | "reserved" {
  const h = handle.trim();
  if (!PAGE_HANDLE_RE.test(h)) return "invalid";
  return RESERVED_PAGE_HANDLES.includes(h.toLowerCase()) ? "reserved" : "ok";
}

export const pageService = {
  async list(params: { q?: string; mine?: boolean; cursor?: string }): Promise<CursorPage<Page>> {
    const { data } = await api.get<CursorPage<Page>>("/pages/", {
      params: { q: params.q || undefined, mine: params.mine ? 1 : undefined, cursor: params.cursor },
    });
    return data;
  },
  /** The visible pages among `ids` (followed or saved pages); others are left out. */
  async byIds(ids: string[]): Promise<Page[]> {
    const out: Page[] = [];
    for (let i = 0; i < ids.length; i += 50) {
      const { data } = await api.get<CursorPage<Page>>("/pages/", { params: { ids: ids.slice(i, i + 50).join(",") } });
      out.push(...data.data);
    }
    const order = new Map(ids.map((id, i) => [id, i]));
    return out.sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0));
  },
  async get(handle: string): Promise<Page> {
    const { data } = await api.get<{ data: Page }>(`/pages/${handle}/`);
    return data.data;
  },
  async getById(id: string): Promise<Page> {
    const { data } = await api.get<{ data: Page }>(`/pages/id/${id}/`);
    return data.data;
  },
  async create(payload: PageCreate): Promise<Page> {
    const { data } = await api.post<{ data: Page }>("/pages/", payload);
    return data.data;
  },
  async update(id: string, payload: PageUpdate): Promise<Page> {
    const { data } = await api.patch<{ data: Page }>(`/pages/id/${id}/`, payload);
    return data.data;
  },
  async members(id: string): Promise<PageMember[]> {
    const { data } = await api.get<{ data: PageMember[] }>(`/pages/id/${id}/members/`);
    return data.data;
  },
  async addMember(id: string, accountId: string, role: string): Promise<PageMember> {
    const { data } = await api.post<{ data: PageMember }>(`/pages/id/${id}/members/`, {
      account_id: accountId,
      role,
    });
    return data.data;
  },
  async setRole(id: string, memberId: string, role: string): Promise<PageMember> {
    const { data } = await api.patch<{ data: PageMember }>(`/pages/id/${id}/members/${memberId}/`, {
      role,
    });
    return data.data;
  },
  async removeMember(id: string, memberId: string): Promise<void> {
    await api.delete(`/pages/id/${id}/members/${memberId}/`);
  },

  // ---- follows (graph) ----
  async follow(id: string): Promise<void> {
    await api.post(`/follows/${id}/`, { target_type: "page" });
  },
  async unfollow(id: string): Promise<void> {
    await api.delete(`/follows/${id}/`, { params: { target_type: "page" } });
  },
  /** Ids of the pages I follow (graph's following list, pages only). */
  async followedIds(): Promise<string[]> {
    const { data } = await api.get<{ data: { following: { target_id: string; target_type: string }[] } }>(
      "/follows/following/",
    );
    return data.data.following.filter((f) => f.target_type === "page").map((f) => f.target_id);
  },

  // ---- saved (post service, item_type "page") ----
  async isSaved(id: string): Promise<boolean> {
    const { data } = await api.get<{ data: { saved: boolean } }>(`/saved/page/${id}/`);
    return data.data.saved;
  },
  async save(id: string): Promise<void> {
    await api.post("/saved/", { item_type: "page", item_id: id });
  },
  async unsave(id: string): Promise<void> {
    await api.delete(`/saved/page/${id}/`);
  },
  /** One page of saved pages, newest save first; pages no longer visible are left out. */
  async savedPage(cursor?: string | null): Promise<{ pages: Page[]; nextCursor: string | null }> {
    const { data } = await api.get<CursorPage<{ item_id: string }>>("/saved/", {
      params: { item_type: "page", cursor: cursor || undefined },
    });
    const ids = data.data.map((s) => s.item_id);
    return { pages: ids.length ? await this.byIds(ids) : [], nextCursor: data.page.next_cursor };
  },

  // ---- moderation ----
  async report(id: string, reason: string): Promise<void> {
    await api.post("/moderation/reports/file/", { target_type: "page", target_id: id, reason });
  },

  // ---- posts as the page (post service) ----
  /** Publish as the page: owners, admins and editors of a published page (the server checks). */
  async createPost(pageId: string, payload: { body: string; media_ids?: string[] }): Promise<Post> {
    const mediaIds = payload.media_ids ?? [];
    const { data } = await api.post<{ data: Post }>("/posts/", {
      type: mediaIds.length ? "image" : "text",
      audience: "public",
      media_ids: mediaIds,
      body: payload.body,
      page_id: pageId,
    });
    return data.data;
  },
  /** The page's timeline: published posts by the page, newest first. */
  async posts(pageId: string, cursor?: string | null): Promise<CursorPage<Post>> {
    const { data } = await api.get<CursorPage<Post>>("/posts/", {
      params: { author_id: pageId, cursor: cursor || undefined },
    });
    return data;
  },
  /** "Page transparency": created date, category and past names (404 when the page is hidden from me). */
  async transparency(pageId: string): Promise<PageTransparency> {
    const { data } = await api.get<{ data: PageTransparency }>(`/pages/id/${pageId}/transparency/`);
    return data.data;
  },
  /** The page's posts with photos (its Photos card), newest first. */
  async photoPosts(pageId: string, cursor?: string | null): Promise<CursorPage<Post>> {
    const { data } = await api.get<CursorPage<Post>>("/posts/", {
      params: { author_id: pageId, media: "photo", cursor: cursor || undefined },
    });
    return data;
  },
  /** Pages I may post as: the identities a composer can offer next to my own name. */
  async postingIdentities(): Promise<Page[]> {
    const { data } = await api.get<CursorPage<Page>>("/pages/", { params: { mine: 1 } });
    return data.data.filter(canPostAs);
  },
};
