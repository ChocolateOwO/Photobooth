import { describe, expect, it } from 'vitest'

import { THEME_CATALOG } from '../../features/admin/testing/themeCatalog.fixture'
import { contrastProblems, contrastRatio, isHexColor, problemMessage, tokenVar } from './theme'

describe('event theme contrast', () => {
  it('measures WCAG contrast like the backend', () => {
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 5)
    expect(contrastRatio('#FFFFFF', '#FFFFFF')).toBeCloseTo(1, 5)
    expect(contrastRatio('#767676', '#FFFFFF')).toBeCloseTo(4.54, 2)
  })

  it('finds no problem in any preset (all meet WCAG AA)', () => {
    expect(THEME_CATALOG.presets.length).toBeGreaterThanOrEqual(6)
    for (const preset of THEME_CATALOG.presets) {
      expect(contrastProblems(preset.tokens, THEME_CATALOG.contrast_rules), preset.id).toEqual([])
    }
  })

  it('reports unreadable manual choices with plain words', () => {
    const base = THEME_CATALOG.presets[0]?.tokens ?? {}
    const tokens = { ...base, heading: base.background ?? '#000000', placeholder: base.input_bg ?? '#000000' }
    const problems = contrastProblems(tokens, THEME_CATALOG.contrast_rules)
    expect(problems.map((p) => p.what)).toEqual(
      expect.arrayContaining(['Headings', 'Example text in inputs']),
    )
    const labels = Object.fromEntries(THEME_CATALOG.tokens.map((t) => [t.key, t.label.toLowerCase()]))
    const heading = problems.find((p) => p.what === 'Headings' && p.background === 'background')
    expect(heading && problemMessage(heading, labels)).toBe(
      'Headings: contrast 1.0:1 is below 4.5:1 (headings on page background).',
    )
  })

  it('names CSS variables after the tokens and checks hex colours', () => {
    expect(tokenVar('primary_disabled_bg')).toBe('--ev-primary-disabled-bg')
    expect(isHexColor('#A1b2C3')).toBe(true)
    expect(isHexColor('red')).toBe(false)
  })
})
