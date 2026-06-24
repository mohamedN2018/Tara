import { api } from "@/lib/api";
import type { CursorPage, Listing, ListingCategory } from "@/types";

export interface ListingQuery {
  q?: string;
  category?: string; // category slug
  condition?: string;
  location?: string;
  min_price?: number;
  max_price?: number;
  cursor?: string;
}

export interface CreateListingPayload {
  category_id: string;
  title: string;
  description?: string;
  price: number;
  currency?: string;
  condition?: string;
  location?: string;
  media_ids?: string[];
}

export type ListingAction = "reserve" | "reactivate" | "mark_sold" | "archive";

// Routes live under /marketplace/listings/ (the marketplace service prefix).
export const marketplaceService = {
  async categories(): Promise<ListingCategory[]> {
    const { data } = await api.get<{ data: ListingCategory[] }>("/marketplace/categories/");
    return data.data;
  },

  async list(query: ListingQuery = {}): Promise<CursorPage<Listing>> {
    const { data } = await api.get<CursorPage<Listing>>("/marketplace/listings/", { params: query });
    return data;
  },

  async myListings(cursor?: string): Promise<CursorPage<Listing>> {
    const { data } = await api.get<CursorPage<Listing>>("/marketplace/my-listings/", {
      params: { cursor },
    });
    return data;
  },

  async savedList(cursor?: string): Promise<CursorPage<Listing>> {
    const { data } = await api.get<CursorPage<Listing>>("/marketplace/saved/", {
      params: { cursor },
    });
    return data;
  },

  async get(id: string): Promise<Listing> {
    const { data } = await api.get<{ data: Listing }>(`/marketplace/listings/${id}/`);
    return data.data;
  },

  async create(payload: CreateListingPayload): Promise<Listing> {
    const { data } = await api.post<{ data: Listing }>("/marketplace/listings/", payload);
    return data.data;
  },

  // New listings start as draft; publishing moves them to active (auto-approve).
  async publish(id: string): Promise<Listing> {
    const { data } = await api.post<{ data: Listing }>(`/marketplace/listings/${id}/publish/`);
    return data.data;
  },

  // Seller status transitions: reserve / reactivate / mark_sold / archive.
  async transition(id: string, action: ListingAction): Promise<Listing> {
    const { data } = await api.post<{ data: Listing }>(`/marketplace/listings/${id}/transition/`, {
      action,
    });
    return data.data;
  },

  // SaveView is POST/DELETE.
  async save(id: string): Promise<void> {
    await api.post(`/marketplace/listings/${id}/save/`);
  },
  async unsave(id: string): Promise<void> {
    await api.delete(`/marketplace/listings/${id}/save/`);
  },

  async report(id: string, reason: string): Promise<void> {
    await api.post(`/marketplace/listings/${id}/report/`, { reason });
  },

  // Contacting a seller emits marketplace.contact.requested, which the chat
  // service consumes to open the conversation (no direct DM endpoint here).
  async contact(id: string, message = ""): Promise<void> {
    await api.post(`/marketplace/listings/${id}/contact/`, { message });
  },
};
