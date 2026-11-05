import { defineStore } from "pinia";
import { ref } from "vue";

import { errorMessage } from "@/lib/errors";

export interface Toast {
  id: number;
  text: string;
  icon?: "bell" | "message" | "error" | "success";
  to?: string; // optional route to navigate to on click
  /** An optional button on the toast (e.g. "Undo"); the toast closes once it runs. */
  action?: { label: string; run: () => void; testid?: string };
}

export const useToastStore = defineStore("toasts", () => {
  const items = ref<Toast[]>([]);
  let seq = 0;

  function push(toast: Omit<Toast, "id">, ttl = 4500) {
    const id = ++seq;
    items.value.push({ ...toast, id });
    window.setTimeout(() => dismiss(id), ttl);
  }
  function dismiss(id: number) {
    items.value = items.value.filter((t) => t.id !== id);
  }

  /** Show a failure, translated from its backend error code. */
  function error(failure: unknown, overrides?: Record<string, string>) {
    push({ text: errorMessage(failure, overrides), icon: "error" }, 6000);
  }
  function success(text: string) {
    push({ text, icon: "success" });
  }

  return { items, push, dismiss, error, success };
});
