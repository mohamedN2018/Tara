import { api, apiError } from "@/lib/api";
import { errorKey, mediaErrorKey } from "@/lib/errors";
import type { CursorPage } from "@/types";

/** The currencies the ads service accepts for a campaign (serializers.CAMPAIGN_CURRENCIES). */
export const CAMPAIGN_CURRENCIES = ["AED", "BHD", "EGP", "EUR", "GBP", "JOD", "KWD", "OMR", "QAR", "SAR", "USD"] as const;

// The field a validation failure is about, to a message.
const FIELD_KEYS: Record<string, string> = {
  currency: "ads.errors.currency",
  schedule_end: "ads.errors.scheduleEnd",
  budget: "ads.errors.budget",
};

/** i18n key for a failed ads call: the field's own message when the server names one. */
export function adErrorKey(error: unknown): string {
  const media = mediaErrorKey(error);
  if (media) return media;
  const { code, details = [] } = apiError(error);
  const field = details.find((d) => d.field && FIELD_KEYS[d.field])?.field;
  if (code === "validation_error" && field) return FIELD_KEYS[field];
  // Media could not be checked (the service fails closed).
  if (code === "dependency_unavailable" || code === "server_error") return "ads.errors.unavailable";
  return errorKey(code);
}

export interface Campaign {
  id: string;
  name: string;
  objective: string;
  budget: string;
  spent: string;
  currency: string;
  status: string; // draft | active | paused | completed
  created_at: string;
}

export interface Creative {
  id: string;
  ad_set_id: string;
  headline: string;
  body: string;
  cta: string;
  link_url: string;
  review_status: string; // pending | approved | rejected
}

export interface AdSet {
  id: string;
  name: string;
  placement: string;
  cpc: string;
  cpm: string;
  frequency_cap: number;
  creatives: Creative[];
}

export interface CampaignReport {
  impressions: number;
  clicks: number;
  ctr: number;
  budget: string;
  spent: string;
  creatives: {
    id: string;
    headline: string;
    review_status: string;
    impressions: number;
    clicks: number;
  }[];
}

export interface ReviewItem extends Creative {
  campaign_name: string;
  advertiser_name: string;
  placement: string;
}

export const adsService = {
  async campaigns(): Promise<Campaign[]> {
    const { data } = await api.get<{ data: Campaign[] }>("/ads/campaigns/");
    return data.data;
  },
  async createCampaign(payload: { name: string; budget: string; currency: string }): Promise<Campaign> {
    const { data } = await api.post<{ data: Campaign }>("/ads/campaigns/", payload);
    return data.data;
  },
  async setStatus(id: string, status: "active" | "paused"): Promise<Campaign> {
    const { data } = await api.patch<{ data: Campaign }>(`/ads/campaigns/${id}/`, { status });
    return data.data;
  },
  async report(id: string): Promise<CampaignReport> {
    const { data } = await api.get<{ data: CampaignReport }>(`/ads/campaigns/${id}/report/`);
    return data.data;
  },
  async adSets(campaignId: string): Promise<AdSet[]> {
    const { data } = await api.get<{ data: AdSet[] }>(`/ads/campaigns/${campaignId}/ad-sets/`);
    return data.data;
  },
  async createAdSet(
    campaignId: string,
    payload: { name: string; placement: string; cpc: string; cpm: string },
  ): Promise<void> {
    await api.post(`/ads/campaigns/${campaignId}/ad-sets/`, payload);
  },
  async createCreative(
    adSetId: string,
    payload: { headline: string; body: string; cta: string; link_url: string },
  ): Promise<void> {
    await api.post(`/ads/ad-sets/${adSetId}/creatives/`, payload);
  },

  async reviewQueue(): Promise<ReviewItem[]> {
    const { data } = await api.get<CursorPage<ReviewItem>>("/ads/review-queue/");
    return data.data;
  },
  async review(id: string, decision: "approved" | "rejected", notes = ""): Promise<void> {
    await api.post(`/ads/creatives/${id}/review/`, { decision, notes });
  },

  /** Report a served ad. The token proves it was served to this viewer. */
  async event(kind: "impression" | "click", creativeId: string, token: string): Promise<void> {
    await api.post(
      "/ads/events/",
      { kind, creative_id: creativeId, token },
      { headers: { "Idempotency-Key": crypto.randomUUID() } },
    );
  },
};
