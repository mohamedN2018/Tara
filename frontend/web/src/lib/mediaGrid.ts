// Layout of a post's photo grid (ported from QTech's PostFeed.vue grid):
//   1 photo  → one wide image
//   2 photos → two squares side by side
//   3 photos → a tall first image beside two stacked ones
//   4+       → a 2×2 grid; the fourth tile shows "+N" for the photos not shown
// CSS grid follows the page direction, so in RTL the first photo sits on the
// right, which is where an Arabic reader starts.

export const GRID_MAX_TILES = 4;

export type GridKind = "none" | "single" | "pair" | "triple" | "quad";

export interface GridTile {
  /** Index of the photo in the post (what the viewer opens). */
  index: number;
  /** Extra classes for this tile's cell. */
  cell: string;
  /** Photos hidden behind this tile ("+N"); 0 for every tile but the last. */
  overflow: number;
}

export interface GridLayout {
  kind: GridKind;
  /** Classes for the grid container. */
  container: string;
  tiles: GridTile[];
}

export function gridLayout(count: number): GridLayout {
  const n = Math.max(0, Math.floor(count));
  if (n === 0) return { kind: "none", container: "", tiles: [] };
  if (n === 1) {
    return { kind: "single", container: "grid-cols-1", tiles: [{ index: 0, cell: "max-h-[32rem]", overflow: 0 }] };
  }
  if (n === 2) {
    return {
      kind: "pair",
      container: "grid-cols-2",
      tiles: [0, 1].map((index) => ({ index, cell: "aspect-square", overflow: 0 })),
    };
  }
  if (n === 3) {
    return {
      kind: "triple",
      container: "h-80 grid-cols-2 grid-rows-2 sm:h-96",
      tiles: [
        { index: 0, cell: "row-span-2 h-full", overflow: 0 },
        { index: 1, cell: "h-full", overflow: 0 },
        { index: 2, cell: "h-full", overflow: 0 },
      ],
    };
  }
  return {
    kind: "quad",
    container: "grid-cols-2",
    tiles: Array.from({ length: GRID_MAX_TILES }, (_, index) => ({
      index,
      cell: "aspect-square",
      overflow: index === GRID_MAX_TILES - 1 ? n - GRID_MAX_TILES : 0,
    })),
  };
}
