// Shared domain types mirroring the backend API contracts (docs/architecture).

export interface Account {
  id: string;
  email: string;
  email_verified: boolean;
  status: string;
  language: string;
  theme: string;
}

export interface Tokens {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_token: string;
}

export interface Profile {
  id?: string;
  user_id?: string;
  handle: string;
  display_name: string;
  avatar_media_id: string | null;
  cover_media_id: string | null;
  bio?: string;
  city?: string;
  country?: string;
  visibility: string;
  is_self?: boolean;
  are_friends?: boolean;
  restricted?: boolean;
}

export interface Post {
  id: string;
  author_id: string;
  author_type: string;
  type: string;
  body: string;
  audience: string;
  media_ids: string[];
  reaction_count: number;
  comment_count: number;
  share_count: number;
  created_at: string;
}

export interface FeedItem {
  id: string;
  post_id: string;
  author_id: string;
  reason: string;
  snapshot: Record<string, unknown>;
  post_created_at: string;
}

export interface SponsoredSlot {
  creative_id: string;
  headline: string;
  body?: string;
  cta?: string;
  sponsored: boolean;
}

export interface Conversation {
  id: string;
  type: string;
  title: string;
  last_message_at: string | null;
  members: string[];
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  type: string;
  body: string;
  attachments: { media_id: string; kind: string; duration_ms: number | null }[];
  created_at: string;
}

export interface Listing {
  id: string;
  seller_id: string;
  title: string;
  description: string;
  price: string;
  currency: string;
  condition: string;
  location: string;
  status: string;
  save_count: number;
  created_at: string;
}

export interface Notification {
  id: string;
  kind: string;
  actor_id: string | null;
  subject_ref: string;
  body: string;
  read_at: string | null;
  created_at: string;
}

export interface CursorPage<T> {
  data: T[];
  page: { next_cursor: string | null; prev_cursor: string | null; has_more: boolean };
}

export interface ApiError {
  code: string;
  message: string;
  request_id?: string;
  details?: { field: string | null; code: string; message: string }[];
}
