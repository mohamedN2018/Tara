import { onUnmounted, type Ref, watch } from "vue";

/**
 * Call `onEscape` when the user presses Escape, but only while `active` is true.
 * Used to make popovers/menus keyboard-dismissable. Listener is attached only
 * when open and cleaned up on unmount.
 */
export function useEscapeKey(active: Ref<boolean>, onEscape: () => void): void {
  const handler = (e: KeyboardEvent) => {
    if (e.key === "Escape") onEscape();
  };
  // Immediate: modals mount already open, so `active` never changes for them.
  watch(
    active,
    (open) => {
      if (open) window.addEventListener("keydown", handler);
      else window.removeEventListener("keydown", handler);
    },
    { immediate: true },
  );
  onUnmounted(() => window.removeEventListener("keydown", handler));
}
