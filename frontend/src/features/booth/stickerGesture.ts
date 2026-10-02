import type { PlacedSticker } from './decorationEditor'

/**
 * Touch gestures on a sticker, as plain geometry.
 *
 * Points are in the finished photo's own pixels (the preview's SVG coordinates), so a gesture
 * means the same whatever size the preview is shown at. One finger moves the sticker; two
 * fingers move it with their midpoint, scale it with their distance and turn it with their angle.
 */

export interface Point {
  readonly x: number
  readonly y: number
}

export interface Canvas {
  readonly width: number
  readonly height: number
}

function midpoint(points: readonly Point[]): Point {
  const sum = points.reduce((acc, p) => ({ x: acc.x + p.x, y: acc.y + p.y }), { x: 0, y: 0 })
  return { x: sum.x / points.length, y: sum.y / points.length }
}

function distance(a: Point, b: Point): number {
  return Math.hypot(b.x - a.x, b.y - a.y)
}

function angle(a: Point, b: Point): number {
  return (Math.atan2(b.y - a.y, b.x - a.x) * 180) / Math.PI
}

/**
 * Where the sticker is now, given where it was when the fingers came down (`start`), where the
 * fingers were then (`from`) and where they are now (`to`, the same fingers in the same order).
 * The result is not clamped: the editor keeps it inside the server's rules.
 */
export function follow(
  start: PlacedSticker,
  from: readonly Point[],
  to: readonly Point[],
  canvas: Canvas,
): PlacedSticker {
  if (from.length === 0 || from.length !== to.length) return start
  const before = midpoint(from)
  const after = midpoint(to)
  let { size, rotation } = start
  if (from.length >= 2) {
    const [a0, b0] = from as [Point, Point]
    const [a1, b1] = to as [Point, Point]
    const spread = distance(a0, b0)
    if (spread > 1) size = start.size * (distance(a1, b1) / spread)
    rotation = start.rotation + (angle(a1, b1) - angle(a0, b0))
  }
  return {
    ...start,
    x: start.x + (after.x - before.x) / canvas.width,
    y: start.y + (after.y - before.y) / canvas.height,
    size,
    rotation,
  }
}
