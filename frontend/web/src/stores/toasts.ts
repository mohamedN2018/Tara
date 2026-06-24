import { defineStore } from "pinia";
import { ref } from "vue";

export interface Toast {
  id: number;
  text: string;
  icon?: "bell" | "message";
  to?: string; // optional route to navigate to on click
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

  return { items, push, dismiss };
});
