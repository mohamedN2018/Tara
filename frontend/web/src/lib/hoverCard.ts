// What a name's hover card shows (PostCard authors, comment authors, search
// results). Everything is fetched lazily, the first time a card opens, from the
// endpoints the profile and page screens already use, so the server's privacy
// rules apply unchanged: a profile that is blocked or hidden answers 404 and
// the card says it is unavailable; counts the owner hides answer 404 and are
// left out, never shown as 0.
import { graphService } from "@/services/graph";
import { pageService } from "@/services/pages";
import { profileService } from "@/services/profile";
import { relationshipsService } from "@/services/relationships";

export type FriendState = "none" | "friends" | "pending_in" | "pending_out";

export interface PersonCard {
  kind: "user";
  id: string;
  name: string;
  handle: string;
  avatar: string | null;
  cover: string | null;
  intro: string;
  city: string;
  followers: number | null;
  mutual: number | null;
}

export interface PageCard {
  kind: "page";
  id: string;
  name: string;
  handle: string;
  avatar: string | null;
  cover: string | null;
  category: string;
  followers: number | null;
  following: boolean | null;
  status: string;
  myRole: string | null;
}

export type CardData = PersonCard | PageCard;

/** The signed-in account's own relationships, loaded once per session for every card. */
export interface MyRelations {
  following: Set<string>;
  friends: Set<string>;
  /** Their request to me: requester id -> request id. */
  incoming: Map<string, string>;
  outgoing: Set<string>;
}

const TTL_MS = 5 * 60 * 1000;
const cards = new Map<string, { at: number; promise: Promise<CardData | null> }>();
let relations: { at: number; promise: Promise<MyRelations> } | null = null;

const now = () => Date.now();

async function loadPerson(id: string): Promise<PersonCard | null> {
  const [profile, counts] = await Promise.allSettled([profileService.getById(id), relationshipsService.counts(id)]);
  if (profile.status === "rejected") return null;
  const p = profile.value;
  const c = counts.status === "fulfilled" ? counts.value : null;
  return {
    kind: "user",
    id,
    name: p.display_name || p.handle || "",
    handle: p.handle || "",
    avatar: p.avatar_media_id ?? null,
    cover: p.cover_media_id ?? null,
    intro: p.intro || "",
    city: p.city || "",
    followers: c ? c.followers_count : null,
    mutual: c ? c.mutual_count : null,
  };
}

async function loadPage(id: string): Promise<PageCard | null> {
  try {
    const p = await pageService.getById(id);
    return {
      kind: "page",
      id,
      name: p.name,
      handle: p.handle,
      avatar: p.avatar_media_id,
      cover: p.cover_media_id,
      category: p.category || "",
      followers: p.followers_count,
      following: p.viewer_following,
      status: p.status,
      myRole: p.my_role,
    };
  } catch {
    return null;
  }
}

/** The card for one person or page (cached for a few minutes; failures are not cached). */
export function cardData(kind: "user" | "page", id: string): Promise<CardData | null> {
  const key = `${kind}:${id}`;
  const hit = cards.get(key);
  if (hit && now() - hit.at < TTL_MS) return hit.promise;
  const promise = (kind === "page" ? loadPage(id) : loadPerson(id)).catch(() => null);
  cards.set(key, { at: now(), promise });
  void promise.then((v) => {
    if (v === null) cards.delete(key);
  });
  return promise;
}

export function myRelations(): Promise<MyRelations> {
  if (relations && now() - relations.at < TTL_MS) return relations.promise;
  const promise = Promise.all([
    graphService.followingIds(),
    graphService.friends(),
    graphService.incomingRequests(),
    graphService.outgoingRequests(),
  ]).then(([following, friends, incoming, outgoing]) => ({
    following: new Set(following),
    friends: new Set(friends),
    incoming: new Map(incoming.map((r) => [r.from_user_id, r.id] as [string, string])),
    outgoing: new Set(outgoing.map((r) => r.to_user_id)),
  }));
  relations = { at: now(), promise };
  promise.catch(() => (relations = null));
  return promise;
}

export function friendState(rel: MyRelations, id: string): FriendState {
  if (rel.friends.has(id)) return "friends";
  if (rel.incoming.has(id)) return "pending_in";
  if (rel.outgoing.has(id)) return "pending_out";
  return "none";
}

/** Forget cached cards and relations (sign-out, tests). */
export function resetHoverCards(): void {
  cards.clear();
  relations = null;
}

let owner = "";
/** Cards and relations belong to one signed-in account: a different one starts afresh. */
export function useCardsOf(accountId: string): void {
  if (accountId !== owner) {
    resetHoverCards();
    owner = accountId;
  }
}

/** Only a real mouse (or trackpad) opens a card on hover: never touch or a pen tap. */
export function canHover(): boolean {
  try {
    return window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  } catch {
    return false;
  }
}
