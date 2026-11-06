// Post-menu feedback with an undo toast (Tara Intelligence R4: 04 WP 7.3, 07 WP 7.5-B2).
//
// One call sends the action to feed (`POST /feed/feedback/`) and shows the 06 §10
// confirmation with "Undo", which deletes that exact row (`DELETE /feed/feedback/{id}/`).
// A caller that removes the item at once (Not interested, Don't recommend this
// creator) passes `onGone` and `onBack`: the item leaves before the server answers
// and comes back when the call fails or the viewer undoes it. Nothing is inferred
// here; the server decides what each action means.
import { feedService, type FeedbackAction, type FeedbackItemType } from "@/services/feed";
import { useToastStore } from "@/stores/toasts";

export interface FeedbackRequest {
  action: FeedbackAction;
  itemType: FeedbackItemType;
  itemId: string;
  surface: string;
  /** `mute_topic` only. */
  topic?: string;
  st?: string;
  /** The confirmation (already translated). */
  text: string;
  undoLabel: string;
  undoneText: string;
  onGone?: () => void;
  onBack?: () => void;
}

/** How long the confirmation (and its Undo) stays: longer than a plain toast. */
export const FEEDBACK_TOAST_MS = 8_000;

/** Actions after which the item leaves the list at once (restored on undo). */
export const REMOVING_ACTIONS: readonly FeedbackAction[] = ["not_interested", "hide_creator"];

export async function sendFeedback(req: FeedbackRequest): Promise<string | null> {
  const toasts = useToastStore();
  req.onGone?.();
  let id: string;
  try {
    const row = await feedService.feedback({
      item_type: req.itemType,
      item_id: req.itemId,
      action: req.action,
      topic: req.topic,
      surface: req.surface,
      st: req.st,
    });
    id = row.id;
  } catch (e) {
    req.onBack?.();
    toasts.error(e);
    return null;
  }
  toasts.push(
    {
      text: req.text,
      icon: "success",
      action: {
        label: req.undoLabel,
        testid: "feedback-undo",
        run: () => void undoFeedback(id, req),
      },
    },
    FEEDBACK_TOAST_MS,
  );
  return id;
}

async function undoFeedback(id: string, req: FeedbackRequest): Promise<void> {
  const toasts = useToastStore();
  try {
    await feedService.undoFeedback(id);
  } catch (e) {
    toasts.error(e);
    return;
  }
  req.onBack?.();
  toasts.success(req.undoneText);
}
