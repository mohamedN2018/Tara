import { api } from "@/lib/api";
import { chatService } from "@/services/chat";
import type { CursorPage, Listing, ListingCategory } from "@/types";

export interface ListingQuery {
  q?: string;
  category?: string; // category slug; includes its sub-categories
  condition?: string; // comma-separated
  price_type?: string; // comma-separated: fixed,negotiable,free
  availability?: string; // comma-separated: available,reserved,sold (default available)
  location?: string;
  currency?: string;
  min_price?: string | number; // on the effective (sale-first) price
  max_price?: string | number;
  sort?: "newest" | "price_asc" | "price_desc";
  /** One seller's public listings (their shop). */
  seller_id?: string;
  cursor?: string;
  limit?: number;
}

export interface CreateListingPayload {
  category_id: string;
  title: string;
  description?: string;
  price_type?: "fixed" | "negotiable" | "free";
  price?: string | number | null;
  sale_price?: string | number | null;
  currency?: string;
  condition?: string;
  location?: string;
  media_ids?: string[];
}

export type ListingAction = "reserve" | "reactivate" | "mark_sold" | "archive";

export interface FacetValue {
  value: string;
  count: number;
}
export interface ListingFacets {
  total: number;
  category: { slug: string; name: string; parent_id: string | null; count: number }[];
  condition: FacetValue[];
  price_type: FacetValue[];
  availability: FacetValue[];
}

export interface ViewerState {
  is_owner: boolean;
  is_saved: boolean;
  has_inquired: boolean;
  can_review: boolean;
  has_reviewed: boolean;
}
/** Why moderation rejected or removed a listing: sent to its seller only. */
export interface ModerationNote {
  case_id: string | null;
  reason: string;
}
// `viewer` is optional so a ListingDetail can stand in wherever a Listing is expected.
export type ListingDetail = Listing & { viewer?: ViewerState; moderation?: ModerationNote | null };

export type ListingStatus =
  | "draft"
  | "pending_review"
  | "active"
  | "reserved"
  | "sold"
  | "rejected"
  | "archived"
  | "removed";

/** The seller's own numbers for the Selling overview. */
export interface SellingSummary {
  counts: Record<ListingStatus, number>;
  views: number;
  saves: number;
  inquiries: number;
}

export type InquiryRole = "buyer" | "seller";
/** One row of the marketplace inbox. `listing` is null once a buyer can no longer open it. */
export interface InquiryRow {
  id: string;
  role: InquiryRole;
  listing_id: string;
  listing: {
    id: string;
    title: string;
    status: string;
    availability: "available" | "reserved" | "sold" | null;
    price_type: "fixed" | "negotiable" | "free";
    price: string | null;
    sale_price: string | null;
    currency: string;
    category_slug: string;
    cover_media_id: string | null;
  } | null;
  counterpart_id: string;
  first_message: string;
  message_count: number;
  created_at: string;
  last_activity_at: string;
}

/** Server codes for a refused photo, to i18n keys. */
export const LISTING_MEDIA_ERRORS: Record<string, string> = {
  too_many_media: "commerce.photos.errors.tooMany",
  duplicate_media: "commerce.photos.errors.duplicate",
  media_not_owned: "commerce.photos.errors.notOwned",
  media_not_ready: "commerce.photos.errors.notReady",
  media_kind_not_allowed: "commerce.photos.errors.kind",
  video_not_supported_yet: "commerce.photos.errors.kind",
};
export const MAX_LISTING_PHOTOS = 10;

export type ResponseHint = "active_today" | "active_this_week" | "active_this_month" | "inactive";
export interface SellerSummary {
  seller_id: string;
  member_since: string;
  active_listings_count: number;
  sold_listings_count: number;
  rating_avg: number | null;
  rating_count: number;
  response_hint: ResponseHint | null;
}

export interface SellerReview {
  id: string;
  listing_id: string;
  listing_title: string | null;
  seller_id: string;
  buyer_id: string;
  rating: number;
  body: string;
  created_at: string;
}

// Routes live under /marketplace/ (the marketplace service prefix).
export const marketplaceService = {
  async categories(): Promise<ListingCategory[]> {
    const { data } = await api.get<{ data: ListingCategory[] }>("/marketplace/categories/");
    return data.data;
  },

  async list(query: ListingQuery = {}): Promise<CursorPage<Listing>> {
    const { data } = await api.get<CursorPage<Listing>>("/marketplace/listings/", { params: query });
    return data;
  },

  /** Counts per dimension; each ignores its own filter so chips never collapse. */
  async facets(query: ListingQuery = {}): Promise<ListingFacets> {
    const filters: ListingQuery = { ...query };
    delete filters.cursor;
    delete filters.limit;
    delete filters.sort;
    const { data } = await api.get<{ data: ListingFacets }>("/marketplace/listings/facets/", {
      params: filters,
    });
    return data.data;
  },

  /** The seller's own listings, optionally only some statuses (comma-separated). */
  async myListings(cursor?: string, status?: string): Promise<CursorPage<Listing>> {
    const { data } = await api.get<CursorPage<Listing>>("/marketplace/my-listings/", {
      params: { cursor, status: status || undefined },
    });
    return data;
  },

  async sellingSummary(): Promise<SellingSummary> {
    const { data } = await api.get<{ data: SellingSummary }>("/marketplace/my-listings/summary/");
    return data.data;
  },

  /** The marketplace inbox: listings I asked about (buyer) or buyers who asked about mine (seller). */
  async inquiries(role: InquiryRole, cursor?: string): Promise<CursorPage<InquiryRow>> {
    const { data } = await api.get<CursorPage<InquiryRow>>("/marketplace/inquiries/", {
      params: { role, cursor },
    });
    return data;
  },

  /** Listings the viewer saved and can still open, newest save first. */
  async savedList(cursor?: string): Promise<CursorPage<Listing>> {
    const { data } = await api.get<CursorPage<Listing>>("/marketplace/saved/", {
      params: { cursor },
    });
    return data;
  },

  async get(id: string): Promise<ListingDetail> {
    const { data } = await api.get<{ data: ListingDetail }>(`/marketplace/listings/${id}/`);
    return data.data;
  },

  /** Up to 4 visible listings in the order asked; hidden ones are left out. */
  async compare(ids: string[]): Promise<Listing[]> {
    if (!ids.length) return [];
    const { data } = await api.get<{ data: Listing[] }>("/marketplace/compare/", {
      params: { ids: ids.slice(0, 4).join(",") },
    });
    return data.data;
  },

  async create(payload: CreateListingPayload): Promise<Listing> {
    const { data } = await api.post<{ data: Listing }>("/marketplace/listings/", payload);
    return data.data;
  },

  async update(id: string, payload: Partial<CreateListingPayload>): Promise<ListingDetail> {
    const { data } = await api.patch<{ data: ListingDetail }>(`/marketplace/listings/${id}/`, payload);
    return data.data;
  },

  // New listings start as draft; publishing moves them to active (or pending review).
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

  /** One view per viewer per cooldown; counted in Redis, never blocks the page. */
  async recordView(id: string): Promise<void> {
    await api.post(`/marketplace/listings/${id}/view/`);
  },

  async report(id: string, reason: string): Promise<void> {
    await api.post(`/marketplace/listings/${id}/report/`, { reason });
  },

  async inquire(id: string, message: string): Promise<{ inquiry_id: string; seller_id: string }> {
    const { data } = await api.post<{ data: { inquiry_id: string; seller_id: string } }>(
      `/marketplace/listings/${id}/inquiries/`,
      { message },
    );
    return data.data;
  },

  /**
   * "Message seller": record the inquiry (it makes the buyer eligible to review)
   * and ask chat for the listing's own marketplace thread (contact/ emits
   * marketplace.contact.requested; one thread per listing and buyer, the one the
   * seller's marketplace inbox opens). Chat creates it from the event, so wait a
   * little; if it never shows (chat behind), the DM still reaches the seller.
   * Sends the message through chat's own API and returns the conversation id.
   */
  async messageSeller(listing: Pick<Listing, "id" | "seller_id">, message: string, link: string, waitMs = 8000) {
    await api.post(`/marketplace/listings/${listing.id}/contact/`, { message });
    const conversation =
      (await chatService.listingThread(listing.id, listing.seller_id, waitMs)) ?? (await chatService.openDm(listing.seller_id));
    const body = [message.trim(), link].filter(Boolean).join("\n");
    await chatService.send(conversation.id, { body });
    return conversation.id;
  },

  async seller(id: string): Promise<SellerSummary> {
    const { data } = await api.get<{ data: SellerSummary }>(`/marketplace/sellers/${id}/`);
    return data.data;
  },

  async sellerReviews(id: string, cursor?: string): Promise<CursorPage<SellerReview>> {
    const { data } = await api.get<CursorPage<SellerReview>>(`/marketplace/sellers/${id}/reviews/`, {
      params: { cursor },
    });
    return data;
  },

  async createReview(listingId: string, rating: number, body: string): Promise<SellerReview> {
    const { data } = await api.post<{ data: SellerReview }>(
      `/marketplace/listings/${listingId}/reviews/`,
      { rating, body },
    );
    return data.data;
  },

  async reportReview(reviewId: string, reason: string): Promise<void> {
    await api.post(`/marketplace/reviews/${reviewId}/report/`, { reason });
  },
};
