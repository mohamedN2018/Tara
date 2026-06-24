import { api } from "@/lib/api";
import type { Conversation, CursorPage, Message } from "@/types";

export const chatService = {
  async conversations(): Promise<Conversation[]> {
    const { data } = await api.get<{ data: Conversation[] }>("/conversations/");
    return data.data;
  },

  async getConversation(id: string): Promise<Conversation> {
    const { data } = await api.get<{ data: Conversation }>(`/conversations/${id}/`);
    return data.data;
  },

  async openDm(userId: string): Promise<Conversation> {
    // DM creation is POST /conversations/ with {type: "dm", other_id}.
    const { data } = await api.post<{ data: Conversation }>("/conversations/", {
      type: "dm",
      other_id: userId,
    });
    return data.data;
  },

  async messages(conversationId: string, cursor?: string): Promise<CursorPage<Message>> {
    const { data } = await api.get<CursorPage<Message>>(
      `/conversations/${conversationId}/messages/`,
      { params: { cursor } },
    );
    return data;
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

  async markRead(conversationId: string, messageId: string): Promise<void> {
    await api.post(`/conversations/${conversationId}/read/`, { up_to_message_id: messageId });
  },
};
