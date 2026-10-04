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
 * The Resize handle: the sticker grows or shrinks about its own centre by how much farther from
 * (or nearer to) that centre the pointer is now than when it came down. Only `size` (the width)
 * changes, so the height follows from the sticker's own shape: the aspect ratio never changes, and
 * neither does the place. Not clamped: the editor keeps it inside the server's rules.
 */
export function resizeFrom(
  start: PlacedSticker,
  centre: Point,
  from: Point,
  to: Point,
): PlacedSticker {
  const before = distance(centre, from)
  if (before < 1) return start
  return { ...start, size: start.size * (distance(centre, to) / before) }
}

export type HandleKind = 'move' | 'resize' | 'remove'

/** Which corner of the sticker each handle is attached to (in the sticker's own turned frame). */
const CORNERS: Record<HandleKind, Point> = {
  move: { x: -1, y: -1 }, // top left
  remove: { x: 1, y: -1 }, // top right
  resize: { x: 1, y: 1 }, // bottom right
}

/**
 * Where each handle sits, in photo pixels: on its corner of the sticker as it is turned, but never
 * so close to the photo's edge that it would be cut off. A sticker pushed into a corner of the
 * photo keeps all its handles on the photo, within reach.
 */
export function handleSpots(
  sticker: PlacedSticker,
  aspect: number,
  canvas: Canvas,
  radius: number,
): Record<HandleKind, Point> {
  const w = sticker.size * canvas.width
  const h = w * aspect
  const cx = sticker.x * canvas.width
  const cy = sticker.y * canvas.height
  const turn = (sticker.rotation * Math.PI) / 180
  const cos = Math.cos(turn)
  const sin = Math.sin(turn)
  const inside = (value: number, size: number) =>
    size <= 2 * radius ? size / 2 : Math.min(size - radius, Math.max(radius, value))
  const spots = {} as Record<HandleKind, Point>
  for (const kind of Object.keys(CORNERS) as HandleKind[]) {
    const corner = CORNERS[kind]
    const dx = (corner.x * w) / 2
    const dy = (corner.y * h) / 2
    spots[kind] = {
      x: inside(cx + dx * cos - dy * sin, canvas.width),
      y: inside(cy + dx * sin + dy * cos, canvas.height),
    }
  }
  if (apart(spots, radius)) return spots
  return beside({ x: cx, y: cy }, w, h, canvas, radius) ?? spots
}

/** The least room between two handle centres: a little more than two radii (no overlap). */
const SPACING = 2.3

function apart(spots: Record<HandleKind, Point>, radius: number): boolean {
  const all = Object.values(spots)
  return all.every((a, i) =>
    all.slice(i + 1).every((b) => distance(a, b) >= SPACING * radius - 1e-6),
  )
}

/**
 * A sticker too small for its corners, or pushed into a corner of the photo, would get its handles
 * on top of each other. They then line up side by side next to it (above, below, then beside it),
 * still on the photo, in the same order: Move, Resize, Remove. Null if the photo is too small for
 * any such row.
 */
function beside(
  centre: Point,
  w: number,
  h: number,
  canvas: Canvas,
  radius: number,
): Record<HandleKind, Point> | null {
  const step = SPACING * radius
  const gap = 1.4 * radius
  const fits = (value: number, low: number, high: number) => value >= low && value <= high
  const extent = Math.max(w, h) / 2
  const rows: { along: 'x' | 'y'; at: number }[] = [
    { along: 'x', at: centre.y - h / 2 - gap }, // above
    { along: 'x', at: centre.y + h / 2 + gap }, // below
    { along: 'y', at: centre.x + w / 2 + gap }, // to the right
    { along: 'y', at: centre.x - w / 2 - gap }, // to the left
    { along: 'y', at: centre.x + Math.min(extent, radius) }, // last resort: over the sticker
  ]
  for (const row of rows) {
    const length = row.along === 'x' ? canvas.width : canvas.height
    const across = row.along === 'x' ? canvas.height : canvas.width
    if (length < 2 * step + 2 * radius) continue
    const at = Math.min(across - radius, Math.max(radius, row.at))
    if (!fits(row.at, radius, across - radius) && row !== rows[rows.length - 1]) continue
    const middle = row.along === 'x' ? centre.x : centre.y
    const first = Math.min(length - radius - 2 * step, Math.max(radius, middle - step))
    const place = (n: number): Point =>
      row.along === 'x' ? { x: first + n * step, y: at } : { x: at, y: first + n * step }
    return { move: place(0), resize: place(1), remove: place(2) }
  }
  return null
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
