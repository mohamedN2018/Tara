import { api } from "@/lib/api";
import { oldestFirst } from "@/lib/chat";
import type { Conversation, CursorPage, Message } from "@/types";

export const chatService = {
  async conversations(): Promise<Conversation[]> {
    return (await this.conversationsPage()).data;
  },

  async conversationsPage(cursor?: string): Promise<CursorPage<Conversation>> {
    const { data } = await api.get<CursorPage<Conversation>>("/conversations/", {
      params: { cursor },
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
      attachments?: Message["attachments"];
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

  async markRead(conversationId: string, messageId: string): Promise<void> {
    await api.post(`/conversations/${conversationId}/read/`, { up_to_message_id: messageId });
  },
};
