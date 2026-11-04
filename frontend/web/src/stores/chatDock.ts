import { defineStore } from "pinia";
import { ref } from "vue";

// Mini chat windows docked at the bottom end of every page but the inbox
// (desktop only): open a conversation from the contacts rail or the New message
// button and keep chatting while browsing. A window is a real conversation; the
// dock only remembers which ones are open, expanded or minimised to a head.

/** Expanded windows side by side; older ones fold into heads. */
export const MAX_EXPANDED = 2;
/** Heads stacked above the New message button. */
export const MAX_HEADS = 5;
/** The dock needs the width of a desktop (Tailwind `lg`). */
export const DOCK_MEDIA = "(min-width: 1024px)";

export interface DockWindow {
  id: string;
  minimised: boolean;
  /** For the minimised head: the chat's title and the other person, once loaded. */
  title?: string;
  peerId?: string;
}

export const useChatDockStore = defineStore("chatDock", () => {
  const windows = ref<DockWindow[]>([]);
  const composing = ref(false);

  /** Whether this screen shows a dock at all (phones go to the inbox instead). */
  function available(): boolean {
    try {
      return typeof window !== "undefined" && !!window.matchMedia?.(DOCK_MEDIA).matches;
    } catch {
      return false;
    }
  }

  function fold() {
    let expanded = 0;
    // Newest first: the newest windows stay open.
    for (const w of windows.value) {
      if (!w.minimised) expanded += 1;
      if (expanded > MAX_EXPANDED && !w.minimised) w.minimised = true;
    }
    if (windows.value.length > MAX_HEADS + MAX_EXPANDED) {
      windows.value = windows.value.slice(0, MAX_HEADS + MAX_EXPANDED);
    }
  }

  /** Open (or bring forward and expand) a conversation's window. */
  function open(id: string) {
    const known = windows.value.find((w) => w.id === id);
    const rest = windows.value.filter((w) => w.id !== id);
    windows.value = [{ ...known, id, minimised: false }, ...rest];
    fold();
  }

  /** The window loaded its conversation: remember what its head shows. */
  function describe(id: string, title: string, peerId = "") {
    const w = windows.value.find((x) => x.id === id);
    if (w) {
      w.title = title;
      w.peerId = peerId;
    }
  }

  function minimise(id: string) {
    const w = windows.value.find((x) => x.id === id);
    if (w) w.minimised = true;
  }

  function close(id: string) {
    windows.value = windows.value.filter((w) => w.id !== id);
  }

  /** Close a window for a conversation the viewer lost (left, blocked, removed). */
  function forget(id: string) {
    close(id);
  }

  function reset() {
    windows.value = [];
    composing.value = false;
  }

  return { windows, composing, available, open, describe, minimise, close, forget, reset };
});
