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

export interface ProfileLink {
  id: number;
  label: string;
  url: string;
  position: number;
}

export interface ProfileEducation {
  id: number;
  school: string;
  degree: string;
  field: string;
  start_year: number | null;
  end_year: number | null;
}

export interface ProfileWork {
  id: number;
  company: string;
  title: string;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
}

export interface Profile {
  id?: string;
  account_id?: string;
  user_id?: string;
  handle: string;
  display_name: string;
  avatar_media_id: string | null;
  cover_media_id: string | null;
  bio?: string;
  intro?: string;
  city?: string;
  country?: string;
  visibility: string;
  completion_pct?: number;
  links?: ProfileLink[];
  education?: ProfileEducation[];
  work?: ProfileWork[];
  created_at?: string;
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
  my_reaction?: string | null;
  is_saved?: boolean;
  created_at: string;
  // Client-side: built from a feed snapshot, so `body` may be a truncated
  // excerpt and it must not be edited.
  partial?: boolean;
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
  member_states: ConversationMemberState[];
  muted_until: string | null;
  pinned_messages: PinnedMessage[];
}

export interface PinnedMessage {
  id: string;
  sender_id: string;
  type: string;
  body: string;
}

export interface MessageReaction {
  account_id: string;
  type: string;
}

export interface ConversationMemberState {
  account_id: string;
  role: string;
  last_read_message_id: string | null;
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  type: string;
  body: string;
  reply_to_id?: string | null;
  attachments: { media_id: string; kind: string; duration_ms: number | null }[];
  reactions: MessageReaction[];
  created_at: string;
  edited_at?: string | null;
}

export interface ListingCategory {
  id: string;
  slug: string;
  name: string;
  parent_id: string | null;
  position: number;
}

export interface ListingMedia {
  media_id: string;
  position: number;
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
  updated_at?: string;
  category?: ListingCategory;
  media?: ListingMedia[];
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
