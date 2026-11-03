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
  /** `{type: count}`, most used first (post service, 1.4). */
  reaction_counts?: Record<string, number>;
  comment_count: number;
  share_count: number;
  /** Who may comment: everyone | friends | off (enforced by the server). */
  comment_policy?: "everyone" | "friends" | "off";
  my_reaction?: string | null;
  is_saved?: boolean;
  link_preview?: LinkPreview | null;
  poll?: Poll | null;
  shared_post_id?: string | null;
  shared_post?: SharedPost | null;
  /** Group posts (1.11): the server forces `audience: "group"`. */
  group_id?: string | null;
  approval_state?: "approved" | "pending";
  pinned_at?: string | null;
  created_at: string;
  // Client-side: built from a feed snapshot, so `body` may be a truncated
  // excerpt and it must not be edited.
  partial?: boolean;
}

export interface LinkPreview {
  url: string;
  title: string;
  description: string;
  site: string;
}

export interface Poll {
  id: string;
  closes_at: string | null;
  closed: boolean;
  total_votes: number;
  my_option_id: string | null;
  options: { id: string; text: string; vote_count: number }[];
}

export interface SharedPost {
  id: string;
  author_id: string;
  author_type: string;
  type: string;
  body: string;
  audience: string;
  media_ids: string[];
  link_preview: LinkPreview | null;
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
  link_url?: string;
  token: string;
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
  /** Per-conversation message sequence; unread = last_seq - my last_read_seq. */
  last_seq?: number;
  /** For the viewer. */
  unread_count?: number;
  archived?: boolean;
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
  last_read_seq?: number;
  last_delivered_seq?: number;
}

export interface MessageAttachment {
  media_id: string;
  kind: string;
  duration_ms: number | null;
  mime?: string;
  bytes?: number | null;
  file_name?: string;
  position?: number;
}

export interface MessageReplyPreview {
  id: string;
  sender_id: string;
  type: string;
  body: string;
  deleted: boolean;
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  type: string;
  body: string;
  /** Per-conversation sequence; null for messages not numbered yet. */
  seq?: number | null;
  reply_to_id?: string | null;
  reply_preview?: MessageReplyPreview | null;
  /** Deleted for everyone: a tombstone with no content. */
  deleted?: boolean;
  forwarded?: boolean;
  attachments: MessageAttachment[];
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
  // Three-state price: null = no price (negotiable, "make an offer"), "0" = free.
  price: string | null;
  price_type?: "fixed" | "negotiable" | "free";
  sale_price?: string | null;
  effective_price?: string | null;
  currency: string;
  price_unconfirmed?: boolean;
  condition: string;
  location: string;
  status: string;
  availability?: "available" | "reserved" | "sold" | null;
  save_count: number;
  view_count?: number;
  inquiry_count?: number;
  is_saved?: boolean;
  created_at: string;
  updated_at?: string;
  category?: ListingCategory;
  media?: ListingMedia[];
}

export interface Notification {
  id: string;
  kind: string;
  /** Registry category: social | connections | messages | marketplace | pages | ads. */
  category?: string;
  /** The most recent actor; `recent_actor_ids` holds up to three, newest first. */
  actor_id: string | null;
  /** Distinct people folded into this row (aggregates: "X and 3 others"). */
  actor_count?: number;
  recent_actor_ids?: string[];
  subject_ref: string;
  target_ref?: string;
  body: string;
  /** Whitelisted ids for links and inline actions (e.g. `request_id`). */
  data?: Record<string, string | number | boolean>;
  /** Same-origin deep link built by the server from the kind registry. */
  url?: string;
  /** Outcome of an inline action: accepted, declined, expired, withdrawn, followed_back. */
  resolution?: string;
  read_at: string | null;
  created_at: string;
  /** When the row last changed (an aggregate moves up as events merge in). */
  last_event_at?: string;
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
