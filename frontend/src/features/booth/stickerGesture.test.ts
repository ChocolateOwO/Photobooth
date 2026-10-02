import { describe, expect, it } from 'vitest'

import type { PlacedSticker } from './decorationEditor'
import { follow } from './stickerGesture'

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
