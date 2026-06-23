import { api } from "@/lib/api";
import type { Profile } from "@/types";

export const profileService = {
  // Public profile by handle is served at /users/<handle>/ (not /profiles/).
  async get(handle: string): Promise<Profile> {
    const { data } = await api.get<{ data: Profile }>(`/users/${handle}/`);
    return data.data;
  },

  async me(): Promise<Profile> {
    const { data } = await api.get<{ data: Profile }>("/profile/me/");
    return data.data;
  },

  async update(payload: Partial<Profile>): Promise<Profile> {
    const { data } = await api.patch<{ data: Profile }>("/profile/me/", payload);
    return data.data;
  },
};
