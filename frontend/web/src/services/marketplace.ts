import { api } from "@/lib/api";
import type { CursorPage, Listing } from "@/types";

export interface ListingQuery {
  q?: string;
  category?: string;
  min_price?: number;
  max_price?: number;
  cursor?: string;
}

// Routes live under /marketplace/listings/ (the marketplace service prefix).
export const marketplaceService = {
  async list(query: ListingQuery = {}): Promise<CursorPage<Listing>> {
    const { data } = await api.get<CursorPage<Listing>>("/marketplace/listings/", { params: query });
    return data;
  },

  async get(id: string): Promise<Listing> {
    const { data } = await api.get<{ data: Listing }>(`/marketplace/listings/${id}/`);
    return data.data;
  },

  async create(payload: Partial<Listing>): Promise<Listing> {
    const { data } = await api.post<{ data: Listing }>("/marketplace/listings/", payload);
    return data.data;
  },

  async save(id: string): Promise<void> {
    await api.put(`/marketplace/listings/${id}/save/`);
  },
  async unsave(id: string): Promise<void> {
    await api.delete(`/marketplace/listings/${id}/save/`);
  },

  // Contacting a seller emits marketplace.contact.requested, which the chat
  // service consumes to open the conversation (no direct DM endpoint here).
  async contact(id: string, message = ""): Promise<void> {
    await api.post(`/marketplace/listings/${id}/contact/`, { message });
  },
};
