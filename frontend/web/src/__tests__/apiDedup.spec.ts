// WP 4c.8-B3, web part (08 §7.11): identical in-flight GETs and idempotent lookup
// POSTs share one request; anything different goes out on its own; nothing is
// kept after the answer.
import type { AxiosAdapter, InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { api, dedupKey, inflightCount } from "@/lib/api";

let sent: InternalAxiosRequestConfig[];
let release: Array<() => void>;
const original = api.defaults.adapter;

beforeEach(() => {
  sent = [];
  release = [];
  const adapter: AxiosAdapter = (config) =>
    new Promise((resolve) => {
      sent.push(config);
      release.push(() =>
        resolve({ data: { data: [{ n: sent.length }] }, status: 200, statusText: "OK", headers: {}, config }),
      );
    });
  api.defaults.adapter = adapter;
});
afterEach(() => {
  api.defaults.adapter = original;
});

const settle = async () => {
  await new Promise((r) => setTimeout(r, 0));
  release.splice(0).forEach((r) => r());
  await new Promise((r) => setTimeout(r, 0));
};

describe("in-flight de-duplication", () => {
  it("shares one GET for the same URL and params (in any key order)", async () => {
    const a = api.get("/feed/", { params: { mode: "recent", cursor: undefined, x: 1 } });
    const b = api.get("/feed/", { params: { x: 1, mode: "recent" } });
    await settle();
    const [ra, rb] = await Promise.all([a, b]);
    expect(sent).toHaveLength(1);
    expect(rb.data).toEqual(ra.data);
    expect(rb.data).not.toBe(ra.data); // each caller has its own copy
    expect(inflightCount()).toBe(0);
  });

  it("does not share GETs with different params, nor after the first one settled", async () => {
    const a = api.get("/feed/", { params: { mode: "recent" } });
    const b = api.get("/feed/", { params: { mode: "for_you" } });
    await settle();
    await Promise.all([a, b]);
    const c = api.get("/feed/", { params: { mode: "recent" } });
    await settle();
    await c;
    expect(sent).toHaveLength(3);
  });

  it("shares a lookup POST with the same ids in another order", async () => {
    const a = api.post("/media/resolve/", { ids: ["b", "a"] });
    const b = api.post("/media/resolve/", { ids: ["a", "b"] });
    await settle();
    await Promise.all([a, b]);
    expect(sent).toHaveLength(1);
  });

  it("does NOT share a POST with a different body", async () => {
    const a = api.post("/posts/batch/", { ids: ["a"] });
    const b = api.post("/posts/batch/", { ids: ["a", "c"] });
    const c = api.post("/users/lookup/", { ids: ["a"] });
    await settle();
    await Promise.all([a, b, c]);
    expect(sent).toHaveLength(3);
  });

  it("never shares a non-idempotent POST", async () => {
    const a = api.post("/posts/", { body: "hi" });
    const b = api.post("/posts/", { body: "hi" });
    await settle();
    await Promise.all([a, b]);
    expect(sent).toHaveLength(2);
  });

  it("keeps per-id hints aligned: ids are not re-sorted when a field follows their order", () => {
    const one = dedupKey("post", "/posts/batch/", undefined, { ids: ["a", "b"], src: ["x", "y"], surface: "home" });
    const two = dedupKey("post", "/posts/batch/", undefined, { ids: ["b", "a"], src: ["y", "x"], surface: "home" });
    expect(one).not.toBe(two);
    expect(dedupKey("get", "/x/", { signal: new AbortController().signal })).toBeNull();
  });

  it("never shares a request that carries its own headers", () => {
    expect(dedupKey("get", "/x/", { headers: { "Idempotency-Key": "k1" } })).toBeNull();
    expect(dedupKey("post", "/media/resolve/", { headers: { "X-Test": "1" } }, { ids: ["a"] })).toBeNull();
    expect(dedupKey("get", "/x/", { headers: {} })).not.toBeNull();
  });

  it("a failure is shared too and then forgotten", async () => {
    api.defaults.adapter = (config) => {
      sent.push(config);
      return Promise.reject(Object.assign(new Error("boom"), { config, response: { status: 503 } }));
    };
    const a = api.get("/x/");
    const b = api.get("/x/");
    await expect(a).rejects.toThrow("boom");
    await expect(b).rejects.toThrow("boom");
    expect(sent).toHaveLength(1);
    expect(inflightCount()).toBe(0);
  });
});
