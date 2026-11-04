// The signed-in account's owner-private relationship lists (mute, restrict,
// favorites) plus blocks, shared by every "..." menu that offers them. Loaded
// once per account and kept in sync by the toggles, so a profile header, a
// friend card and the Connections lists never disagree.
import { reactive } from "vue";

import { graphService } from "@/services/graph";
import { type Preference, relationshipsService } from "@/services/relationships";
import { useAuthStore } from "@/stores/auth";

export type PrefKind = Preference | "blocks";
const KINDS: PrefKind[] = ["mutes", "restricted", "favorites", "blocks"];

interface PrefState {
  owner: string;
  loaded: Record<PrefKind, boolean>;
  ids: Record<PrefKind, Set<string>>;
  busy: Record<string, boolean>;
}

const state = reactive<PrefState>({
  owner: "",
  loaded: { mutes: false, restricted: false, favorites: false, blocks: false },
  ids: { mutes: new Set(), restricted: new Set(), favorites: new Set(), blocks: new Set() },
  busy: {},
});
const inflight: Partial<Record<PrefKind, Promise<void>>> = {};

function fetchList(kind: PrefKind): Promise<string[]> {
  return kind === "blocks" ? graphService.blockedIds() : relationshipsService.list(kind);
}

/** Test hook: forget everything (the next call reloads). */
export function resetRelationshipPrefs() {
  state.owner = "";
  for (const k of KINDS) {
    state.loaded[k] = false;
    state.ids[k] = new Set();
    delete inflight[k];
  }
  state.busy = {};
}

export function useRelationshipPrefs() {
  const auth = useAuthStore();

  function sameOwner() {
    const me = auth.account?.id ?? "";
    if (state.owner !== me) {
      resetRelationshipPrefs();
      state.owner = me;
    }
  }

  /** Load the given lists (all by default). A failed list stays unloaded, so its item stays hidden. */
  async function ensure(kinds: PrefKind[] = KINDS): Promise<void> {
    sameOwner();
    await Promise.all(
      kinds.map((kind) => {
        if (state.loaded[kind]) return Promise.resolve();
        inflight[kind] ??= fetchList(kind)
          .then((ids) => {
            state.ids[kind] = new Set(ids);
            state.loaded[kind] = true;
          })
          .catch(() => {})
          .finally(() => delete inflight[kind]);
        return inflight[kind];
      }),
    );
  }

  const has = (kind: PrefKind, id: string) => state.ids[kind].has(id);
  const loaded = (kind: PrefKind) => state.loaded[kind];
  const isBusy = (kind: PrefKind, id: string) => !!state.busy[`${kind}:${id}`];
  const list = (kind: PrefKind) => [...state.ids[kind]];

  /** Add or remove `id` on a list. Resolves to the new membership; throws (after rolling back) on failure. */
  async function set(kind: PrefKind, id: string, on: boolean): Promise<boolean> {
    sameOwner();
    const key = `${kind}:${id}`;
    if (state.busy[key]) return has(kind, id);
    state.busy[key] = true;
    const before = new Set(state.ids[kind]);
    const next = new Set(before);
    if (on) next.add(id);
    else next.delete(id);
    state.ids[kind] = next;
    // Mute and favorite exclude each other on the server; mirror it here.
    const other = kind === "mutes" ? "favorites" : kind === "favorites" ? "mutes" : null;
    const otherBefore = other ? new Set(state.ids[other]) : null;
    if (on && other) {
      const o = new Set(state.ids[other]);
      o.delete(id);
      state.ids[other] = o;
    }
    // A block ends favorites both ways.
    const favBefore = kind === "blocks" ? new Set(state.ids.favorites) : null;
    if (on && kind === "blocks") {
      const f = new Set(state.ids.favorites);
      f.delete(id);
      state.ids.favorites = f;
    }
    try {
      if (kind === "blocks") await (on ? graphService.block(id) : graphService.unblock(id));
      else await (on ? relationshipsService.add(kind, id) : relationshipsService.remove(kind, id));
      return on;
    } catch (e) {
      state.ids[kind] = before;
      if (other && otherBefore) state.ids[other] = otherBefore;
      if (favBefore) state.ids.favorites = favBefore;
      throw e;
    } finally {
      delete state.busy[key];
    }
  }

  const toggle = (kind: PrefKind, id: string) => set(kind, id, !has(kind, id));

  return { ensure, has, loaded, isBusy, list, set, toggle };
}
