/**
 * Keyboard support shared by the top-bar menus (MainMenu, ProfileMenu), kept
 * free of Vue so it is unit-tested on a plain DOM.
 *
 * ArrowDown/ArrowUp move between the menu items and wrap; Home/End jump. They
 * are vertical, so they mean the same in RTL and LTR. Focus outside the items
 * (the search field, the trigger) enters at the first item on ArrowDown and at
 * the last on ArrowUp. A roving tabindex keeps one item in the Tab order.
 */
export const MENU_ITEM_SELECTOR = '[role="menuitem"], [role="menuitemradio"], [role="menuitemcheckbox"]';

/** The focusable menu items inside `root`, in DOM order. */
export function menuItems(root: ParentNode): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(MENU_ITEM_SELECTOR)).filter(
    (el) => !el.hasAttribute("disabled") && el.getAttribute("aria-disabled") !== "true",
  );
}

/** Index of the item a key moves to, or `null` for keys the menu does not handle. */
export function nextMenuIndex(current: number, count: number, key: string): number | null {
  if (count <= 0) return null;
  switch (key) {
    case "ArrowDown":
      return current < 0 || current >= count - 1 ? 0 : current + 1;
    case "ArrowUp":
      return current <= 0 ? count - 1 : current - 1;
    case "Home":
      return 0;
    case "End":
      return count - 1;
    default:
      return null;
  }
}

/** Make `active` the single item reachable with Tab. */
export function setRovingItem(items: HTMLElement[], active: HTMLElement | null): void {
  items.forEach((el, i) => el.setAttribute("tabindex", el === active || (!active && i === 0) ? "0" : "-1"));
}

/**
 * Handle a keydown inside a menu: move focus and return true when the key was
 * used (the caller then calls `preventDefault`). Home/End are left to a text
 * field that has focus, so the caret still moves there.
 */
export function handleMenuKey(root: ParentNode, event: Pick<KeyboardEvent, "key" | "target">): boolean {
  const items = menuItems(root);
  const target = event.target as HTMLElement | null;
  const current = target ? items.indexOf(target) : -1;
  const inField = !!target && current < 0 && (target.tagName === "INPUT" || target.tagName === "TEXTAREA");
  if (inField && (event.key === "Home" || event.key === "End")) return false;
  const next = nextMenuIndex(current, items.length, event.key);
  if (next === null) return false;
  setRovingItem(items, items[next]);
  items[next].focus();
  return true;
}
