import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { applyMatrix, matrixValues } from './colorMatrix'

/**
 * Filter parity with the server. The same fixture is checked by the backend against Pillow
 * (backend/tests/unit/test_decoration_render.py): every colour must come out of the booth's
 * feColorMatrix as it comes out of the server, within one step of 255.
 */

interface Fixture {
  filters: Record<string, number[]>
  cases: { filter: string; input: [number, number, number]; expected: [number, number, number] }[]
}

function read(relative: string): string {
  // A variable, not a literal: Vite would turn `new URL('literal', import.meta.url)` into a URL.
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')
}

const FIXTURE = JSON.parse(read('../../../../backend/tests/fixtures/decoration_parity.json')) as Fixture

describe('filter parity with the server', () => {
  it('covers every filter the server offers', () => {
    expect(Object.keys(FIXTURE.filters)).toEqual(['none', 'mono', 'sepia', 'warm', 'cool', 'bright'])
    expect(FIXTURE.cases.length).toBeGreaterThanOrEqual(30)
  })

  it.each(FIXTURE.cases)('$filter turns $input into $expected', ({ filter, input, expected }) => {
    const out = applyMatrix(FIXTURE.filters[filter] ?? [], input)
    out.forEach((value, channel) => {
      expect(Math.abs(value - (expected[channel] ?? -9))).toBeLessThanOrEqual(1)
    })
  })

  it('lays the API rows out as feColorMatrix rows, alpha untouched', () => {
    expect(matrixValues([1, 2, 3, 0.5, 4, 5, 6, 0.25, 7, 8, 9, -0.1])).toBe(
      '1 2 3 0 0.5 4 5 6 0 0.25 7 8 9 0 -0.1 0 0 0 1 0',
    )
  })
})
