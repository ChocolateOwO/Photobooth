import type { CSSProperties } from 'react'

import type { ContrastRule } from '../api/adminClient'

/**
 * Event themes on the client: every semantic token becomes a CSS custom property
 * (`primary_bg` -> `--ev-primary-bg`) set on an event-facing container only, so the admin shell
 * never follows the event theme. Contrast is measured exactly like the backend (WCAG 2.x).
 */

export type ThemeTokens = Record<string, string>

export function tokenVar(key: string): string {
  return `--ev-${key.replaceAll('_', '-')}`
}

export function themeStyle(tokens: ThemeTokens): CSSProperties {
  const style: Record<string, string> = {}
  for (const [key, value] of Object.entries(tokens)) {
    style[tokenVar(key)] = value
  }
  return style as CSSProperties
}

const HEX = /^#[0-9a-fA-F]{6}$/

export function isHexColor(value: string): boolean {
  return HEX.test(value)
}

function channel(value: number): number {
  const c = value / 255
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

export function luminance(hex: string): number {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

export function contrastRatio(a: string, b: string): number {
  const la = luminance(a)
  const lb = luminance(b)
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

export interface ContrastProblem {
  what: string
  foreground: string
  background: string
  ratio: number
  minimum: number
}

/** Every rule the tokens break (unknown or malformed colours are skipped; the server refuses them). */
export function contrastProblems(tokens: ThemeTokens, rules: ContrastRule[]): ContrastProblem[] {
  const found: ContrastProblem[] = []
  for (const rule of rules) {
    const fg = tokens[rule.foreground]
    const bg = tokens[rule.background]
    if (!fg || !bg || !isHexColor(fg) || !isHexColor(bg)) continue
    const ratio = contrastRatio(fg, bg)
    if (ratio + 1e-9 < rule.minimum) {
      found.push({ ...rule, ratio })
    }
  }
  return found
}

export function problemMessage(problem: ContrastProblem, labels: Record<string, string>): string {
  const fg = labels[problem.foreground] ?? problem.foreground
  const bg = labels[problem.background] ?? problem.background
  return `${problem.what}: contrast ${problem.ratio.toFixed(1)}:1 is below ${problem.minimum}:1 (${fg} on ${bg}).`
}
