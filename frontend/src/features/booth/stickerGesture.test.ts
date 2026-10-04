import { describe, expect, it } from 'vitest'

import type { PlacedSticker } from './decorationEditor'
import { follow, handleSpots, resizeFrom } from './stickerGesture'

const CANVAS = { width: 600, height: 1800 }
const START: PlacedSticker = {
  id: 1,
  sticker: 'heart',
  output: 1,
  x: 0.5,
  y: 0.5,
  size: 0.3,
  rotation: 10,
}

describe('sticker gestures', () => {
  it('one finger moves the sticker by as much as the finger moved, in photo fractions', () => {
    const moved = follow(START, [{ x: 300, y: 900 }], [{ x: 360, y: 720 }], CANVAS)
    expect(moved.x).toBeCloseTo(0.6)
    expect(moved.y).toBeCloseTo(0.4)
    expect(moved).toMatchObject({ size: 0.3, rotation: 10 })
  })

  it('two fingers spreading apart make it bigger in proportion', () => {
    const from = [
      { x: 250, y: 900 },
      { x: 350, y: 900 },
    ]
    const to = [
      { x: 200, y: 900 },
      { x: 400, y: 900 },
    ]
    const moved = follow(START, from, to, CANVAS)
    expect(moved.size).toBeCloseTo(0.6)
    expect(moved.x).toBeCloseTo(0.5) // the midpoint did not move
    expect(moved.rotation).toBeCloseTo(10)
  })

  it('two fingers turning clockwise turn it clockwise', () => {
    const from = [
      { x: 250, y: 900 },
      { x: 350, y: 900 },
    ]
    // The second finger swings down (y grows downwards on screen): a clockwise quarter turn.
    const to = [
      { x: 300, y: 850 },
      { x: 300, y: 950 },
    ]
    const moved = follow(START, from, to, CANVAS)
    expect(moved.rotation).toBeCloseTo(100)
    expect(moved.size).toBeCloseTo(0.3)
  })

  it('fingers that do not match leave the sticker where it was', () => {
    expect(follow(START, [], [], CANVAS)).toBe(START)
    expect(follow(START, [{ x: 1, y: 1 }], [], CANVAS)).toBe(START)
  })

  it('two fingers on the same spot never divide by nothing', () => {
    const spot = [
      { x: 300, y: 900 },
      { x: 300, y: 900 },
    ]
    const moved = follow(START, spot, spot, CANVAS)
    expect(moved.size).toBe(0.3)
    expect(Number.isFinite(moved.rotation)).toBe(true)
  })
})

describe('sticker handles', () => {
  const centre = { x: 300, y: 900 }

  it('Resize scales about the centre by the pointer distance, changing nothing else', () => {
    const bigger = resizeFrom(START, centre, { x: 400, y: 900 }, { x: 500, y: 900 })
    expect(bigger.size).toBeCloseTo(0.6)
    expect(bigger).toMatchObject({ x: 0.5, y: 0.5, rotation: 10 })
    // The direction does not matter, only the distance: a turned sticker scales the same way.
    const diagonal = resizeFrom(START, centre, { x: 360, y: 980 }, { x: 330, y: 940 })
    expect(diagonal.size).toBeCloseTo(0.15)
    // A pointer on the very centre never divides by nothing.
    expect(resizeFrom(START, centre, centre, { x: 500, y: 500 })).toBe(START)
  })

  it('handles sit on the corners and turn with the sticker', () => {
    const flat = { ...START, rotation: 0 }
    // 0.3 of 600 = 180 wide; aspect 0.5: 90 tall.
    expect(handleSpots(flat, 0.5, CANVAS, 10)).toEqual({
      move: { x: 210, y: 855 },
      remove: { x: 390, y: 855 },
      resize: { x: 390, y: 945 },
    })
    const quarter = handleSpots({ ...START, rotation: 90 }, 0.5, CANVAS, 10)
    // Turned a quarter clockwise, the top left corner is now at the top right.
    expect(quarter.move.x).toBeCloseTo(345)
    expect(quarter.move.y).toBeCloseTo(810)
    expect(quarter.resize.x).toBeCloseTo(255)
    expect(quarter.resize.y).toBeCloseTo(990)
  })

  it('handles never leave the photo, however close to its edge the sticker is', () => {
    const corner = handleSpots({ ...START, x: 0, y: 1, rotation: 0 }, 0.5, CANVAS, 24)
    for (const spot of Object.values(corner)) {
      expect(spot.x).toBeGreaterThanOrEqual(24)
      expect(spot.x).toBeLessThanOrEqual(600 - 24)
      expect(spot.y).toBeGreaterThanOrEqual(24)
      expect(spot.y).toBeLessThanOrEqual(1800 - 24)
    }
  })
})

describe('handles never cover each other (review R1)', () => {
  // A 600 x 1800 strip shown 200 pixels wide: a 24-pixel handle is 72 photo pixels.
  const radius = 72
  const spots = [0, 0.5, 1].flatMap((x) =>
    [0, 0.5, 1].flatMap((y) =>
      [0, 37, 90, -135].map((rotation) => ({ x, y, rotation })),
    ),
  )

  it.each([0.05, 0.12, 0.32])('a sticker of size %s gets three separate handles, on the photo', (size) => {
    for (const where of spots) {
      const handles = handleSpots({ ...START, size, ...where }, 0.9, CANVAS, radius)
      const all = Object.values(handles)
      for (const spot of all) {
        expect(spot.x).toBeGreaterThanOrEqual(radius - 1e-6)
        expect(spot.x).toBeLessThanOrEqual(600 - radius + 1e-6)
        expect(spot.y).toBeGreaterThanOrEqual(radius - 1e-6)
        expect(spot.y).toBeLessThanOrEqual(1800 - radius + 1e-6)
      }
      for (let i = 0; i < all.length; i++) {
        for (let j = i + 1; j < all.length; j++) {
          const a = all[i] as { x: number; y: number }
          const b = all[j] as { x: number; y: number }
          expect(Math.hypot(a.x - b.x, a.y - b.y), JSON.stringify({ size, where })).toBeGreaterThanOrEqual(
            2 * radius,
          )
        }
      }
    }
  })

  it('a large sticker away from the edges keeps its handles on its corners', () => {
    const big = handleSpots({ ...START, size: 0.6, rotation: 0 }, 0.5, CANVAS, radius)
    expect(big).toEqual({
      move: { x: 120, y: 810 },
      remove: { x: 480, y: 810 },
      resize: { x: 480, y: 990 },
    })
  })
})
