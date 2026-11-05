import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type App, createApp, defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import ComposerDialog from "@/components/post/ComposerDialog.vue";
import { i18n } from "@/i18n";
import { api } from "@/lib/api";
import { fromLocalInput, scheduleBounds, scheduleProblem, toLocalInput } from "@/services/composer";
import { mediaService } from "@/services/media";
import { videoService } from "@/services/video";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";

const Blank = defineComponent({ render: () => null });
let app: App | null = null;
let host: HTMLElement | null = null;

async function flush() {
  for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0));
}

const created = (extra: Record<string, unknown> = {}) => ({
  data: {
    data: {
      id: "p1",
      author_id: "me-1",
      author_type: "user",
      type: "text",
      body: "hello",
      audience: "public",
      media_ids: [],
      reaction_count: 0,
      comment_count: 0,
      share_count: 0,
      created_at: "2026-11-04T10:00:00Z",
      state: "published",
      ...extra,
    },
  },
});

interface Mounted {
  root: HTMLElement;
  events: Record<string, unknown[][]>;
}

async function mount(props: Record<string, unknown> = {}): Promise<Mounted> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/home", component: Blank },
      { path: "/u/id/:id", name: "profile-by-id", component: Blank },
      { path: "/:rest(.*)*", component: Blank },
    ],
  });
  await router.push("/home");
  await router.isReady();
  const events: Record<string, unknown[][]> = { close: [], published: [], saved: [] };
  host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({
    render: () =>
      h(ComposerDialog, {
        ...props,
        onClose: (...a: unknown[]) => events.close.push(a),
        onPublished: (...a: unknown[]) => events.published.push(a),
        onSaved: (...a: unknown[]) => events.saved.push(a),
      }),
  });
  app.use(createPiniaOnce()).use(router).use(i18n);
  app.mount(host);
  await flush();
  return { root: document.body, events };
}

let pinia = createPinia();
const createPiniaOnce = () => pinia;

const $ = (sel: string) => document.body.querySelector<HTMLElement>(sel);
const byTestId = (id: string) => $(`[data-testid="${id}"]`);
const buttons = () => Array.from(document.body.querySelectorAll<HTMLButtonElement>("[data-testid=composer-dialog] button"));
const buttonNamed = (text: string) => buttons().find((b) => b.textContent?.trim() === text);

async function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  el.value = value;
  el.dispatchEvent(new Event("input"));
  await flush();
}

async function click(el: HTMLElement | null | undefined) {
  expect(el).toBeTruthy();
  el!.click();
  await flush();
}

beforeEach(() => {
  pinia = createPinia();
  setActivePinia(pinia);
  localStorage.clear();
  i18n.global.locale.value = "en";
  const auth = useAuthStore();
  auth.account = { id: "me-1", email: "me@example.com" } as never;
});

afterEach(() => {
  app?.unmount();
  host?.remove();
  app = null;
  host = null;
});

describe("schedule helpers", () => {
  it("round-trips the picker's local time to an ISO instant", () => {
    const at = new Date(2026, 10, 20, 9, 30);
    expect(toLocalInput(at)).toBe("2026-11-20T09:30");
    expect(fromLocalInput("2026-11-20T09:30")).toBe(at.toISOString());
    expect(fromLocalInput("")).toBeNull();
  });

  it("judges a time as the server does: future, at most 75 days ahead", () => {
    const now = new Date(2026, 10, 4, 12, 0);
    expect(scheduleProblem(toLocalInput(new Date(2026, 10, 4, 11, 0)), now)).toBe("past");
    expect(scheduleProblem(toLocalInput(new Date(2026, 10, 5, 12, 0)), now)).toBeNull();
    expect(scheduleProblem(toLocalInput(new Date(2027, 0, 30, 12, 0)), now)).toBe("far");
    const { min, max } = scheduleBounds(now);
    expect(min).toBe("2026-11-04T12:01");
    expect(max).toBe(toLocalInput(new Date(now.getTime() + 75 * 86_400_000)));
  });
});

describe("ComposerDialog", () => {
  it("publishes a post with the audience, a feeling and a location", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue(created());
    const { events } = await mount();
    await type($("textarea")! as HTMLTextAreaElement, "hello world");

    await click(byTestId("composer-audience"));
    await click(Array.from(document.querySelectorAll<HTMLElement>("[role=radio]")).find((r) => r.textContent?.includes("Friends")));
    await click(byTestId("composer-feeling"));
    await click(buttons().find((b) => b.getAttribute("aria-pressed") !== null && b.textContent?.includes("feeling happy")));
    await click(byTestId("composer-location-toggle"));
    await type(byTestId("composer-location") as HTMLInputElement, "  Cairo ");
    expect(byTestId("composer-summary")?.textContent).toContain("feeling happy");

    await click(byTestId("composer-submit"));
    expect(post).toHaveBeenCalledWith("/posts/", expect.objectContaining({
      body: "hello world",
      audience: "friends",
      feeling: "happy",
      location: "Cairo",
    }));
    const payload = post.mock.calls[0][1] as Record<string, unknown>;
    expect(payload).not.toHaveProperty("draft");
    expect(payload).not.toHaveProperty("publish_at");
    expect(events.published).toHaveLength(1);
    expect(events.close).toHaveLength(1);
  });

  it("saves a draft without publishing it", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue(created({ state: "draft" }));
    const { events } = await mount();
    await type($("textarea")! as HTMLTextAreaElement, "for later");
    await click(byTestId("composer-save-draft"));
    expect(post.mock.calls[0][1]).toMatchObject({ body: "for later", draft: true });
    expect(events.published).toHaveLength(0);
    expect(events.saved).toHaveLength(1);
    expect(useToastStore().items.map((t) => t.text)).toContain("Saved to your drafts.");
  });

  it("schedules in the viewer's time zone and refuses a past time", async () => {
    const at = new Date(Date.now() + 2 * 3_600_000);
    const post = vi.spyOn(api, "post").mockResolvedValue(created({ state: "scheduled", publish_at: at.toISOString() }));
    const { events } = await mount();
    await type($("textarea")! as HTMLTextAreaElement, "soon");
    await click(byTestId("composer-schedule"));

    const picker = byTestId("composer-schedule-at") as HTMLInputElement;
    await type(picker, toLocalInput(new Date(Date.now() - 3_600_000)));
    expect(document.body.textContent).toContain("Pick a time in the future.");
    expect((byTestId("composer-schedule-done") as HTMLButtonElement).disabled).toBe(true);

    await type(picker, toLocalInput(at));
    await click(byTestId("composer-schedule-done"));
    expect(byTestId("composer-schedule-summary")).toBeTruthy();
    expect(byTestId("composer-submit")?.textContent?.trim()).toBe("Schedule post");

    await click(byTestId("composer-submit"));
    const payload = post.mock.calls[0][1] as Record<string, unknown>;
    expect(payload.publish_at).toBe(fromLocalInput(toLocalInput(at)));
    expect(payload).not.toHaveProperty("draft");
    expect(events.saved).toHaveLength(1);
    expect(events.published).toHaveLength(0);
  });

  it("tags friends found by name", async () => {
    vi.spyOn(api, "get").mockImplementation(async (url: string) => {
      if (url === "/friends/") return { data: { data: { friends: ["f1", "f2"] } } };
      return { data: { data: [], page: { next_cursor: null, has_more: false } } };
    });
    const post = vi.spyOn(api, "post").mockImplementation(async (url: string) => {
      if (url === "/users/lookup/") {
        return {
          data: {
            data: [
              { account_id: "f1", handle: "sara", display_name: "Sara Ali", avatar_media_id: null },
              { account_id: "f2", handle: "omar", display_name: "Omar", avatar_media_id: null },
            ],
          },
        };
      }
      return created();
    });
    await mount();
    await type($("textarea")! as HTMLTextAreaElement, "trip");
    await click(byTestId("composer-tag"));
    await type(byTestId("composer-friend-search") as HTMLInputElement, "sar");
    const rows = byTestId("composer-friends")!.querySelectorAll("li label");
    expect(rows).toHaveLength(1);
    await click(rows[0].querySelector("input"));
    await click(buttonNamed("Done"));
    expect(byTestId("composer-summary")?.textContent).toContain("with Sara Ali");

    await click(byTestId("composer-submit"));
    const call = post.mock.calls.find((c) => c[0] === "/posts/")!;
    expect(call[1]).toMatchObject({ tagged_ids: ["f1"] });
  });

  it("explains a refused tag", async () => {
    vi.spyOn(api, "post").mockRejectedValue({
      response: { status: 400, data: { error: { code: "tag_not_allowed", message: "x" } } },
    });
    const { events } = await mount();
    await type($("textarea")! as HTMLTextAreaElement, "hi");
    await click(byTestId("composer-submit"));
    expect($("[role=alert]")?.textContent).toBe("You can't tag one of these people.");
    expect(events.close).toHaveLength(0);
  });

  it("offers no drafts or scheduling in a group, and posts into it", async () => {
    const post = vi.spyOn(api, "post").mockResolvedValue(created({ group_id: "g1", audience: "group" }));
    await mount({ groupId: "g1", groupName: "Riders" });
    expect(byTestId("composer-save-draft")).toBeNull();
    expect(byTestId("composer-schedule")).toBeNull();
    expect(byTestId("composer-drafts")).toBeNull();
    expect(byTestId("composer-audience")).toBeNull();
    expect(($("textarea") as HTMLTextAreaElement).placeholder).toBe(i18n.global.t("groups.composer.placeholder"));
    await type($("textarea")! as HTMLTextAreaElement, "group hello");
    await click(byTestId("composer-submit"));
    const payload = post.mock.calls[0][1] as Record<string, unknown>;
    expect(payload).toMatchObject({ group_id: "g1", body: "group hello" });
  });

  it("lists drafts, edits one and publishes it", async () => {
    const draft = { ...created({ id: "d1", body: "old text", state: "draft", updated_at: "2026-11-04T09:00:00Z" }).data.data };
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: [draft], page: { next_cursor: null, has_more: false } } });
    const patch = vi.spyOn(api, "patch").mockResolvedValue({ data: { data: { ...draft, body: "new text" } } });
    const post = vi.spyOn(api, "post").mockResolvedValue(created({ id: "d1", body: "new text" }));
    const { events } = await mount({ start: "drafts" });

    const list = byTestId("composer-drafts-list")!;
    expect(list.textContent).toContain("old text");
    expect(list.textContent).toContain("Draft");
    await click(Array.from(list.querySelectorAll("button")).find((b) => b.textContent?.trim() === "Edit"));
    const editor = $("textarea") as HTMLTextAreaElement;
    expect(editor.value).toBe("old text");
    expect(document.getElementById("composer-title")?.textContent).toBe("Edit draft");
    await type(editor, "new text");
    await click(byTestId("composer-submit"));

    expect(patch).toHaveBeenCalledWith("/posts/drafts/d1/", expect.objectContaining({ body: "new text", publish_at: null }));
    expect(post).toHaveBeenCalledWith("/posts/drafts/d1/publish/");
    expect(events.published).toHaveLength(1);
  });

  it("deletes a draft after a confirmation", async () => {
    const draft = { ...created({ id: "d2", body: "bye", state: "scheduled", publish_at: "2026-12-01T10:00:00Z" }).data.data };
    vi.spyOn(api, "get").mockResolvedValue({ data: { data: [draft], page: { next_cursor: null, has_more: false } } });
    const del = vi.spyOn(api, "delete").mockResolvedValue({ data: null });
    await mount({ start: "drafts" });
    const list = byTestId("composer-drafts-list")!;
    expect(list.textContent).toContain("Scheduled");
    await click(list.querySelector<HTMLElement>("button[aria-label^='Delete']"));
    expect(list.textContent).toContain("Delete this draft for good?");
    await click(Array.from(list.querySelectorAll("button")).find((b) => b.textContent?.trim() === "Delete"));
    expect(del).toHaveBeenCalledWith("/posts/drafts/d2/");
    expect(list.textContent).toContain("No drafts or scheduled posts.");
  });

  it("closes on Escape, and steps back from a sub-view first", async () => {
    const { events } = await mount();
    await click(byTestId("composer-feeling"));
    const panel = $("[role=dialog]")!;
    panel.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await flush();
    expect(document.getElementById("composer-title")?.textContent).toBe("Create post");
    expect(events.close).toHaveLength(0);
    panel.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await flush();
    expect(events.close).toHaveLength(1);
  });

  describe("with a video", () => {
    const VIDEO_ID = "01a1a55d-05d8-76fb-93a7-03b04162793a";
    const asset = { id: VIDEO_ID } as Awaited<ReturnType<typeof videoService.upload>>;
    const draft = { ...created({ id: "d1", body: "old text", state: "draft", updated_at: "2026-11-04T09:00:00Z" }).data.data };
    function deferred<T>() {
      let resolve!: (v: T) => void;
      const promise = new Promise<T>((r) => (resolve = r));
      return { promise, resolve };
    }
    function serve() {
      vi.spyOn(api, "get").mockImplementation(async (url: string) => {
        if (url === "/posts/drafts/") return { data: { data: [draft], page: { next_cursor: null, has_more: false } } };
        return { data: { data: [] } };
      });
      // Playback is batched over POST, which these tests mock for the post itself.
      vi.spyOn(videoService, "playback").mockResolvedValue({
        id: VIDEO_ID, status: "ready", failure_code: null, duration_ms: 1000, width: 640, height: 360, hls_url: "/api/v1/media/x/hls/master.m3u8?token=t", mp4_url: null, poster_url: null, expires_in: 300,
      });
    }
    async function pickVideo() {
      const input = $("[data-testid=composer-video-input]") as HTMLInputElement;
      Object.defineProperty(input, "files", { value: [new File(["v"], "clip.mp4", { type: "video/mp4" })], configurable: true });
      input.dispatchEvent(new Event("change"));
      await flush();
    }
    const photoInput = () => $("[data-testid=composer-dialog] input[type=file][multiple]") as HTMLInputElement | null;

    it("keeps photos out while a video uploads, and sends only the video", async () => {
      serve();
      const upload = deferred<typeof asset>();
      vi.spyOn(videoService, "upload").mockReturnValue(upload.promise);
      const photo = vi.spyOn(mediaService, "upload");
      const post = vi.spyOn(api, "post").mockResolvedValue(created({ type: "video", media_ids: [VIDEO_ID] }));
      await mount();
      await type($("textarea") as HTMLTextAreaElement, "my clip");
      expect(photoInput()).not.toBeNull();
      await pickVideo();
      expect(byTestId("video-attachment")?.dataset.state).toBe("uploading");
      // No photo picker during the upload, and nothing can be posted yet.
      expect(photoInput()).toBeNull();
      expect((byTestId("composer-submit") as HTMLButtonElement).disabled).toBe(true);
      expect((byTestId("composer-save-draft") as HTMLButtonElement).disabled).toBe(true);

      upload.resolve(asset);
      await flush();
      expect(byTestId("video-attachment")?.dataset.state).toBe("ready");
      expect(photoInput()).toBeNull();
      await click(byTestId("composer-submit"));
      expect(photo).not.toHaveBeenCalled();
      expect(post).toHaveBeenCalledWith("/posts/", expect.objectContaining({ media_ids: [VIDEO_ID], type: "video" }));
    });

    it("drops a new post's video when a draft is opened for editing", async () => {
      serve();
      vi.spyOn(videoService, "upload").mockResolvedValue(asset);
      const patch = vi.spyOn(api, "patch").mockResolvedValue({ data: { data: draft } });
      vi.spyOn(api, "post").mockResolvedValue(created({ id: "d1", body: "old text" }));
      await mount();
      await pickVideo();
      expect(byTestId("video-attachment")?.dataset.state).toBe("ready");
      expect(byTestId("video-player")).not.toBeNull();

      await click(byTestId("composer-drafts"));
      await click(Array.from(byTestId("composer-drafts-list")!.querySelectorAll("button")).find((b) => b.textContent?.trim() === "Edit"));
      expect(byTestId("video-player")).toBeNull();
      expect(byTestId("video-attachment")?.dataset.state).toBe("idle");
      expect((byTestId("composer-submit") as HTMLButtonElement).disabled).toBe(false);
      await click(byTestId("composer-submit"));
      expect(patch).toHaveBeenCalledWith("/posts/drafts/d1/", expect.objectContaining({ body: "old text" }));
    });

    it("does not let a video still uploading land in an opened draft", async () => {
      serve();
      const upload = deferred<typeof asset>();
      vi.spyOn(videoService, "upload").mockReturnValue(upload.promise);
      await mount();
      await pickVideo();
      expect(byTestId("video-attachment")?.dataset.state).toBe("uploading");
      await click(byTestId("composer-drafts"));
      await click(Array.from(byTestId("composer-drafts-list")!.querySelectorAll("button")).find((b) => b.textContent?.trim() === "Edit"));
      upload.resolve(asset);
      await flush();
      expect(byTestId("video-player")).toBeNull();
      expect(byTestId("video-attachment")?.dataset.state).toBe("idle");
      expect((byTestId("composer-submit") as HTMLButtonElement).disabled).toBe(false);
    });
  });

  it("renders right to left in Arabic", async () => {
    i18n.global.locale.value = "ar";
    await mount();
    expect(document.getElementById("composer-title")?.textContent).toBe("إنشاء منشور");
    expect(($("textarea") as HTMLTextAreaElement).getAttribute("dir")).toBe("auto");
    expect(byTestId("composer-submit")?.textContent?.trim()).toBe("نشر");
  });
});
