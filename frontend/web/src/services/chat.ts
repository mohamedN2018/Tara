import { api } from "@/lib/api";
import { oldestFirst } from "@/lib/chat";
import { mediaService, type MediaAsset, viaStorageProxy } from "@/services/media";
import type { Conversation, CursorPage, Message, MessageAttachment } from "@/types";

export interface UnreadSummary {
  messages: number;
  conversations: number;
}

export interface SharedMediaItem {
  id: string;
  media_id: string;
  kind: string;
  mime: string;
  bytes: number | null;
  file_name: string;
  duration_ms: number | null;
  message_id: string;
  sender_id: string;
  created_at: string;
}

export interface AttachmentUrl {
  media_id: string;
  message_id: string;
  kind: string;
  mime: string;
  status: string;
  url: string | null;
  thumb_url: string | null;
  file_name: string;
  bytes: number | null;
  duration_ms: number | null;
}

// Chat attachments are private: chat mints presigned URLs after checking that
// the viewer is a member who can see the message. URLs live ~15 min, so they
// are cached for less than that.
const urlCache = new Map<string, { value: AttachmentUrl; at: number }>();
const URL_TTL_MS = 10 * 60 * 1000;

export const chatService = {
  async conversations(): Promise<Conversation[]> {
    return (await this.conversationsPage()).data;
  },

  /** The inbox, or the archived folder with `archived: true`. */
  async conversationsPage(cursor?: string, archived = false): Promise<CursorPage<Conversation>> {
    const { data } = await api.get<CursorPage<Conversation>>("/conversations/", {
      params: { cursor, archived: archived ? 1 : undefined },
    });
    return data;
  },

  async openDm(userId: string): Promise<Conversation> {
    // DM creation is POST /conversations/ with {type: "dm", other_id}.
    const { data } = await api.post<{ data: Conversation }>("/conversations/", {
      type: "dm",
      other_id: userId,
    });
    return data.data;
  },

  /**
   * One page of history, returned oldest first. The API pages newest first, so
   * `page.next_cursor` leads to OLDER messages.
   */
  async messages(conversationId: string, cursor?: string): Promise<CursorPage<Message>> {
    const { data } = await api.get<CursorPage<Message>>(
      `/conversations/${conversationId}/messages/`,
      { params: { cursor } },
    );
    return { ...data, data: oldestFirst(data.data) };
  },

  async send(
    conversationId: string,
    payload: {
      body: string;
      type?: string;
      attachments?: MessageAttachment[];
      reply_to_id?: string | null;
    },
  ): Promise<Message> {
    const { data } = await api.post<{ data: Message }>(
      `/conversations/${conversationId}/messages/`,
      { type: "text", attachments: [], ...payload },
    );
    return data.data;
  },

  async sendVoice(conversationId: string, mediaId: string, durationMs: number): Promise<Message> {
    const { data } = await api.post<{ data: Message }>(
      `/conversations/${conversationId}/voice-messages/`,
      { media_id: mediaId, duration_ms: durationMs },
    );
    return data.data;
  },

  /** Chat media is always uploaded private; only chat can hand out its URLs. */
  async upload(file: File, kind: string): Promise<MediaAsset> {
    return mediaService.upload(file, kind, "private");
  },

  async get(conversationId: string): Promise<Conversation> {
    const { data } = await api.get<{ data: Conversation }>(`/conversations/${conversationId}/`);
    return data.data;
  },

  async createGroup(title: string, memberIds: string[]): Promise<Conversation> {
    const { data } = await api.post<{ data: Conversation }>("/conversations/", {
      type: "group",
      title,
      member_ids: memberIds,
    });
    return data.data;
  },
  async renameGroup(conversationId: string, title: string): Promise<void> {
    await api.patch(`/conversations/${conversationId}/`, { title });
  },
  async addMembers(conversationId: string, accountIds: string[]): Promise<Conversation> {
    const { data } = await api.post<{ data: Conversation }>(
      `/conversations/${conversationId}/members/`,
      { account_ids: accountIds },
    );
    return data.data;
  },
  async removeMember(conversationId: string, accountId: string): Promise<void> {
    await api.delete(`/conversations/${conversationId}/members/${accountId}/`);
  },
  async setMemberRole(conversationId: string, accountId: string, role: string): Promise<void> {
    await api.patch(`/conversations/${conversationId}/members/${accountId}/`, { role });
  },

  async react(messageId: string, type: string): Promise<void> {
    await api.post(`/messages/${messageId}/reactions/`, { type });
  },
  async unreact(messageId: string): Promise<void> {
    await api.delete(`/messages/${messageId}/reactions/`);
  },

  /** 0 unmutes. */
  async mute(conversationId: string, minutes: number): Promise<void> {
    await api.post(`/conversations/${conversationId}/mute/`, { minutes });
  },
  async pin(conversationId: string, messageId: string): Promise<void> {
    await api.post(`/conversations/${conversationId}/pin/`, { message_id: messageId });
  },
  async unpin(conversationId: string, messageId: string): Promise<void> {
    await api.delete(`/conversations/${conversationId}/pin/`, { data: { message_id: messageId } });
  },

  // ---- read state ----

  async markRead(conversationId: string, messageId: string): Promise<void> {
    await api.post(`/conversations/${conversationId}/read/`, { up_to_message_id: messageId });
  },
  /** Everything that reached this device so far is delivered. */
  async markDelivered(): Promise<void> {
    await api.post("/conversations/delivered/");
  },
  async unread(): Promise<UnreadSummary> {
    const { data } = await api.get<{ data: UnreadSummary }>("/conversations/unread/");
    return data.data;
  },

  // ---- inbox state ----

  async archive(conversationId: string, archived: boolean): Promise<Conversation> {
    const { data } = await api.post<{ data: Conversation }>(
      `/conversations/${conversationId}/archive/`,
      { archived },
    );
    return data.data;
  },
  /** Clear chat for me: earlier messages disappear for the caller only. */
  async clear(conversationId: string): Promise<void> {
    await api.post(`/conversations/${conversationId}/clear/`);
  },

  // ---- message lifecycle ----

  async message(messageId: string): Promise<Message> {
    const { data } = await api.get<{ data: Message }>(`/messages/${messageId}/`);
    return data.data;
  },
  async edit(messageId: string, body: string): Promise<Message> {
    const { data } = await api.patch<{ data: Message }>(`/messages/${messageId}/`, { body });
    return data.data;
  },
  async deleteMessage(messageId: string, scope: "me" | "everyone"): Promise<void> {
    await api.delete(`/messages/${messageId}/`, { params: { scope } });
  },
  async forward(messageId: string, conversationIds: string[]): Promise<Message[]> {
    const { data } = await api.post<{ data: Message[] }>(`/messages/${messageId}/forward/`, {
      conversation_ids: conversationIds,
    });
    return data.data;
  },

  // ---- search and shared media ----

  async search(query: string, cursor?: string): Promise<CursorPage<Message>> {
    const { data } = await api.get<CursorPage<Message>>("/messages/search/", {
      params: { q: query, cursor },
    });
    return data;
  },
  async searchIn(conversationId: string, query: string, cursor?: string): Promise<CursorPage<Message>> {
    const { data } = await api.get<CursorPage<Message>>(
      `/conversations/${conversationId}/search/`,
      { params: { q: query, cursor } },
    );
    return data;
  },
  async sharedMedia(
    conversationId: string,
    kind?: string,
    cursor?: string,
  ): Promise<CursorPage<SharedMediaItem>> {
    const { data } = await api.get<CursorPage<SharedMediaItem>>(
      `/conversations/${conversationId}/media/`,
      { params: { kind, cursor } },
    );
    return data;
  },

  /** A presigned URL for one attachment (cached; null `url` while processing). */
  async attachmentUrl(messageId: string, mediaId: string): Promise<AttachmentUrl | null> {
    const key = `${messageId}:${mediaId}`;
    const cached = urlCache.get(key);
    if (cached && Date.now() - cached.at < URL_TTL_MS) return cached.value;
    try {
      const { data } = await api.get<{ data: AttachmentUrl }>(
        `/messages/${messageId}/attachments/${mediaId}/`,
      );
      const value = {
        ...data.data,
        url: viaStorageProxy(data.data.url),
        thumb_url: viaStorageProxy(data.data.thumb_url),
      };
      if (value.url) urlCache.set(key, { value, at: Date.now() });
      return value;
    } catch {
      return cached?.value ?? null;
    }
  },
};
