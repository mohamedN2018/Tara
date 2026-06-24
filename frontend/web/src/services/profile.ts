import { api } from "@/lib/api";
import type { Profile, ProfileEducation, ProfileLink, ProfileWork } from "@/types";

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

  // ---- structured detail sections (own profile) ----
  // These use DRF generics; tolerate both raw and {data:…}-wrapped responses.
  async addLink(payload: { label: string; url: string; position?: number }): Promise<ProfileLink> {
    const { data } = await api.post<ProfileLink | { data: ProfileLink }>("/profile/me/links/", payload);
    return "data" in data ? data.data : data;
  },
  async removeLink(id: number): Promise<void> {
    await api.delete(`/profile/me/links/${id}/`);
  },

  async addEducation(payload: Partial<ProfileEducation>): Promise<ProfileEducation> {
    const { data } = await api.post<ProfileEducation | { data: ProfileEducation }>(
      "/profile/me/education/",
      payload,
    );
    return "data" in data ? data.data : data;
  },
  async removeEducation(id: number): Promise<void> {
    await api.delete(`/profile/me/education/${id}/`);
  },

  async addWork(payload: Partial<ProfileWork>): Promise<ProfileWork> {
    const { data } = await api.post<ProfileWork | { data: ProfileWork }>("/profile/me/work/", payload);
    return "data" in data ? data.data : data;
  },
  async removeWork(id: number): Promise<void> {
    await api.delete(`/profile/me/work/${id}/`);
  },
};
