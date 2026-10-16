// Grid cell (x, y) -> world position in metres. 1 cell = 1 m; the grid is centred on the origin.
// Grid y maps to world z; world y is up.

export const CELL = 1;

export function gridToWorld(x: number, y: number, width: number, height: number): [number, number, number] {
  return [(x - width / 2 + 0.5) * CELL, 0, (y - height / 2 + 0.5) * CELL];
}
