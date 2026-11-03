import { api } from "@/lib/api";
import type { CursorPage } from "@/types";

export interface Page {
  id: string;
  handle: string;
  name: string;
  category: string;
  description: string;
  location: string;
  status: string;
  avatar_media_id: string | null;
  owner_account_id: string;
  my_role: string | null;
  created_at: string;
}

export interface PageMember {
  id: string;
  account_id: string;
  role: string;
}

export const PAGE_ROLES = ["admin", "editor", "moderator", "advertiser", "analyst"];

export const pageService = {
  async list(params: { q?: string; mine?: boolean; cursor?: string }): Promise<CursorPage<Page>> {
    const { data } = await api.get<CursorPage<Page>>("/pages/", {
      params: { q: params.q || undefined, mine: params.mine ? 1 : undefined, cursor: params.cursor },
    });
    return data;
  },
  async get(handle: string): Promise<Page> {
    const { data } = await api.get<{ data: Page }>(`/pages/${handle}/`);
    return data.data;
  },
  async create(payload: {
    handle: string;
    name: string;
    category?: string;
    description?: string;
    location?: string;
  }): Promise<Page> {
    const { data } = await api.post<{ data: Page }>("/pages/", payload);
    return data.data;
  },
  async update(id: string, payload: Partial<Page>): Promise<Page> {
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
};
