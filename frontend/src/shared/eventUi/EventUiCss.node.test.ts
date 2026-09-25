import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

/**
 * Static check of the event UI stylesheet (compiled with Node types, see tsconfig.node.json):
 * every event-facing component takes its colours from the right theme token and nothing else.
 */

function read(relative: string): string {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')
}

const CSS = read('./EventUi.module.css').replace(/\/\*[\s\S]*?\*\//g, '')
const FIXTURE = read('../../features/admin/testing/themeCatalog.fixture.ts')
const CATALOG = JSON.parse(FIXTURE.slice(FIXTURE.indexOf('= ') + 2)) as {
  tokens: { key: string }[]
}

const tokenVar = (key: string) => `--ev-${key.replaceAll('_', '-')}`

function rules(css: string): Map<string, string> {
  const found = new Map<string, string>()
  for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    for (const selector of (match[1] ?? '').split(',')) {
      const key = selector.trim()
      found.set(key, `${found.get(key) ?? ''}${(match[2] ?? '').replace(/\s+/g, ' ')}`)
    }
  }
  return found
}

const RULES = rules(CSS)

describe('event UI stylesheet', () => {
  it('has no hard-coded colours at all (nor does the participant frame carousel)', () => {
    expect(CSS.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/g)).toBeNull()
    const carousel = read('./FrameCarousel.module.css').replace(/\/\*[\s\S]*?\*\//g, '')
    expect(carousel.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/g)).toBeNull()
    const start = read('./StartScreen.module.css').replace(/\/\*[\s\S]*?\*\//g, '')
    expect(start.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/g)).toBeNull()
    expect(start).toContain('var(--ev-heading)')
  })

  it('the admin preview and the real booth draw the same StartScreen component', () => {
    const shared = "from '../../../shared/eventUi/StartScreen'"
    expect(read('../../features/admin/components/EventPreview.tsx')).toContain(`import { StartScreen } ${shared}`)
    const booth = read('../../features/booth/BoothStartPage.tsx')
    expect(booth).toContain("import { StartScreen } from '../../shared/eventUi/StartScreen'")
    // No second copy of the start screen anywhere else.
    expect(booth).not.toMatch(/Email|subtitle|title/)
  })

  it('the admin preview and the real booth draw the same frame carousel', () => {
    expect(read('../../features/admin/components/EventPreview.tsx')).toContain(
      "import { FrameCarousel } from '../../../shared/eventUi/FrameCarousel'",
    )
    expect(read('../../features/booth/FrameSelectPage.tsx')).toContain(
      "import { FrameCarousel } from '../../shared/eventUi/FrameCarousel'",
    )
    // The old grid of cards is gone, with no copy left anywhere. (The path is built from a
    // variable: a literal would be turned into an asset URL when this file is bundled.)
    const grid = './FrameGallery.tsx'
    expect(existsSync(fileURLToPath(new URL(grid, import.meta.url)))).toBe(false)
  })

  it('the carousel shows one whole frame at a time and respects reduced motion', () => {
    const carousel = read('./FrameCarousel.module.css')
    expect(carousel).toContain('scroll-snap-type: y mandatory')
    expect(carousel).toContain('scroll-snap-align: center')
    expect(carousel).toContain('scroll-snap-stop: always')
    expect(carousel).toContain('object-fit: contain') // never cropped or stretched
    expect(carousel).toContain('overscroll-behavior: contain') // the page never drifts
    expect(carousel).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*scroll-behavior: auto/)
  })

  it.each([
    ['.screen', { 'background-color': 'background', color: 'body' }],
    ['.heading', { color: 'heading' }],
    ['.body', { color: 'body' }],
    ['.muted', { color: 'muted' }],
    ['.link', { color: 'link' }],
    ['.primary', { 'background-color': 'primary_bg', color: 'primary_text' }],
    [".primary[data-demo-state='hover']", { 'background-color': 'primary_hover' }],
    [".primary[data-demo-state='pressed']", { 'background-color': 'primary_pressed' }],
    ['.primary:disabled', { 'background-color': 'primary_disabled_bg', color: 'primary_disabled_text' }],
    ['.secondary', { 'background-color': 'secondary_bg', color: 'secondary_text' }],
    [".secondary[data-demo-state='hover']", { 'background-color': 'secondary_hover' }],
    [".secondary[data-demo-state='pressed']", { 'background-color': 'secondary_pressed' }],
    [
      '.secondary:disabled',
      { 'background-color': 'secondary_disabled_bg', color: 'secondary_disabled_text' },
    ],
    ['.danger', { 'background-color': 'danger_bg', color: 'danger_text' }],
    ['.input', { 'background-color': 'input_bg', color: 'input_text', border: 'input_border' }],
    ['.input::placeholder', { color: 'placeholder' }],
    ['.input[data-demo-focus]', { 'border-color': 'input_focus_border' }],
    ['.button:focus-visible', { outline: 'focus_ring' }],
    ['.card', { 'background-color': 'surface' }],
    ['.dialog', { 'background-color': 'surface' }],
    ['.backdrop', { 'background-color': 'overlay' }],
    ['.success', { 'background-color': 'success_bg', color: 'success_text' }],
    ['.warning', { 'background-color': 'warning_bg', color: 'warning_text' }],
    ['.error', { 'background-color': 'error_bg', color: 'error_text' }],
    ['.info', { 'background-color': 'info_bg', color: 'info_text' }],
  ] as const)('%s uses the right tokens', (selector, expected) => {
    const text = RULES.get(selector)
    expect(text, selector).toBeDefined()
    for (const [property, token] of Object.entries(expected)) {
      expect(text).toMatch(new RegExp(`${property}:[^;]*var\\(${tokenVar(token)}\\)`))
    }
  })

  it('uses every semantic token somewhere', () => {
    expect(CATALOG.tokens.length).toBeGreaterThanOrEqual(30)
    for (const token of CATALOG.tokens) {
      expect(CSS, token.key).toContain(`var(${tokenVar(token.key)})`)
    }
  })
})
