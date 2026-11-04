// The studio layout owns one composer; its pages open it through this context
// and reload when `version` changes (something was posted, saved or scheduled).
import { inject, type InjectionKey, type Ref, ref } from "vue";

import type { ComposerPost } from "@/services/composer";

export interface ComposeOptions {
  /** Edit this draft or scheduled post. */
  draft?: ComposerPost | null;
  /** A new post pre-scheduled at this instant. */
  scheduleAt?: string | null;
}

export interface StudioComposer {
  open: (options?: ComposeOptions) => void;
  /** Bumped after every publish, save or schedule from the studio's composer. */
  version: Ref<number>;
  /** Pages bump it after their own writes, so the other panes refresh too. */
  touch: () => void;
}

export const STUDIO_COMPOSER: InjectionKey<StudioComposer> = Symbol("studio-composer");

/** The layout's composer, or an inert stand-in outside the studio (tests). */
export function useStudioComposer(): StudioComposer {
  return (
    inject(STUDIO_COMPOSER, null) ?? {
      open: () => {},
      version: ref(0),
      touch: () => {},
    }
  );
}
