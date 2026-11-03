import { onBeforeUnmount, type Ref, watch } from "vue";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Keep keyboard focus inside a modal while it is rendered. Moves focus in when
 * the element appears and hands it back to the previous element when it goes.
 */
export function useFocusTrap(container: Ref<HTMLElement | null>): void {
  let previous: HTMLElement | null = null;

  const focusable = (el: HTMLElement) => Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE));

  function onKeydown(e: KeyboardEvent) {
    const el = container.value;
    if (e.key !== "Tab" || !el) return;
    const items = focusable(el);
    if (!items.length) {
      e.preventDefault();
      el.focus();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || !el.contains(active))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (active === last || !el.contains(active))) {
      e.preventDefault();
      first.focus();
    }
  }

  function release() {
    document.removeEventListener("keydown", onKeydown);
    previous?.focus();
    previous = null;
  }

  watch(
    container,
    (el) => {
      if (el) {
        previous = document.activeElement as HTMLElement | null;
        document.addEventListener("keydown", onKeydown);
        (focusable(el)[0] ?? el).focus();
      } else {
        release();
      }
    },
    { flush: "post" },
  );

  onBeforeUnmount(release);
}
