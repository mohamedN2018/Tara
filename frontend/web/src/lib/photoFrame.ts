// Geometry for framing photos (plan 08, profile track): the theater's zoom,
// the cover's drag-to-reposition and the avatar's crop. Pure functions, so the
// components stay thin and the maths is unit tested.

export const ZOOM_STEPS = [1, 1.5, 2, 3] as const;
export const MAX_ZOOM = ZOOM_STEPS[ZOOM_STEPS.length - 1];

/** The next zoom step in or out (`dir` +1 / -1); stays at the ends. */
export function stepZoom(current: number, dir: 1 | -1): number {
  if (dir > 0) return ZOOM_STEPS.find((z) => z > current + 1e-6) ?? MAX_ZOOM;
  const lower = [...ZOOM_STEPS].reverse().find((z) => z < current - 1e-6);
  return lower ?? 1;
}

export interface Point {
  x: number;
  y: number;
}

/** Keep a zoomed photo's pan inside what its extra size allows (`box`: the photo's size at zoom 1). */
export function clampPan(pan: Point, zoom: number, box: { width: number; height: number }): Point {
  const maxX = Math.max(0, (box.width * zoom - box.width) / 2);
  const maxY = Math.max(0, (box.height * zoom - box.height) / 2);
  return { x: clamp(pan.x, -maxX, maxX), y: clamp(pan.y, -maxY, maxY) };
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/**
 * The cover's vertical position (CSS `object-position: 50% <y>%`, 0 = top) after
 * dragging it `dy` pixels (down is positive) from `startY`. `frame` is the
 * cover's box and `natural` the photo's own size; a photo no taller than the
 * frame (relative to its width) can't move up or down, so it keeps `startY`.
 */
export function coverOffsetAfterDrag(
  startY: number,
  dy: number,
  frame: { width: number; height: number },
  natural: { width: number; height: number },
): number {
  if (!natural.width || !natural.height || !frame.width || !frame.height) return startY;
  const scale = Math.max(frame.width / natural.width, frame.height / natural.height);
  const overflow = natural.height * scale - frame.height;
  if (overflow <= 0.5) return startY;
  // Dragging down shows more of the top: the percentage goes down.
  return Math.round(clamp(startY - (dy / overflow) * 100, 0, 100));
}

/** A cover offset from the server (or anything else) as a usable 0–100 value. */
export function normaliseCoverOffset(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? Math.round(clamp(n, 0, 100)) : 50;
}

/** `object-position` for a cover at `offset` percent. */
export function coverPosition(offset: unknown): string {
  return `50% ${normaliseCoverOffset(offset)}%`;
}

/**
 * Avatar crop. The photo fills a square `view` (px) at zoom 1 and is moved by
 * `offset` (its centre relative to the view's centre, px). Keeps it covering
 * the square.
 */
export function clampCropOffset(
  offset: Point,
  zoom: number,
  natural: { width: number; height: number },
  view: number,
): Point {
  const s = cropScale(zoom, natural, view);
  const maxX = Math.max(0, (natural.width * s - view) / 2);
  const maxY = Math.max(0, (natural.height * s - view) / 2);
  return { x: clamp(offset.x, -maxX, maxX), y: clamp(offset.y, -maxY, maxY) };
}

export function cropScale(zoom: number, natural: { width: number; height: number }, view: number): number {
  const shortest = Math.min(natural.width, natural.height) || 1;
  return (view / shortest) * Math.max(1, zoom);
}

/** The square of the original photo (natural px) that the view shows. */
export function cropSourceRect(
  offset: Point,
  zoom: number,
  natural: { width: number; height: number },
  view: number,
): { sx: number; sy: number; size: number } {
  const s = cropScale(zoom, natural, view);
  const o = clampCropOffset(offset, zoom, natural, view);
  const left = view / 2 + o.x - (natural.width * s) / 2;
  const top = view / 2 + o.y - (natural.height * s) / 2;
  const size = Math.min(view / s, natural.width, natural.height);
  return {
    sx: clamp(-left / s, 0, natural.width - size),
    sy: clamp(-top / s, 0, natural.height - size),
    size,
  };
}
