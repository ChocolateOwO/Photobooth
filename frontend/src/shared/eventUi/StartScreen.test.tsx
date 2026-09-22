import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { THEME_CATALOG } from '../../features/admin/testing/themeCatalog.fixture'
import { StartScreen } from './StartScreen'

const TOKENS = THEME_CATALOG.presets[0]?.tokens ?? {}

describe('StartScreen', () => {
  it('shows only one centred logo and one Start button', async () => {
    const onStart = vi.fn()
    render(
      <StartScreen
        tokens={TOKENS}
        backgroundImageUrl="/bg.jpg"
        logoUrl="/logo.png"
        startText="Let's go"
        onStart={onStart}
      />,
    )
    const screenEl = screen.getByRole('group', { name: 'Start screen' })
    expect(screenEl.style.backgroundImage).toContain('/bg.jpg')
    expect(within(screenEl).getAllByRole('img')).toHaveLength(1)
    expect(within(screenEl).getByRole('img', { name: 'Event logo' })).toHaveAttribute('src', '/logo.png')
    expect(within(screenEl).getAllByRole('button')).toHaveLength(1)
    expect(within(screenEl).queryByRole('textbox')).toBeNull()
    await userEvent.click(within(screenEl).getByRole('button', { name: "Let's go" }))
    expect(onStart).toHaveBeenCalledTimes(1)
  })

  it('uses the neutral Photobooth mark without a logo, or when the logo fails to load', () => {
    const { rerender } = render(<StartScreen tokens={TOKENS} startText="" />)
    expect(screen.getByRole('img', { name: 'Photobooth' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start' })).toBeInTheDocument() // empty text falls back

    rerender(<StartScreen tokens={TOKENS} logoUrl="/missing.png" startText="Start" />)
    fireEvent.error(screen.getByRole('img', { name: 'Event logo' }))
    expect(screen.queryByRole('img', { name: 'Event logo' })).toBeNull()
    expect(screen.getByRole('img', { name: 'Photobooth' })).toBeInTheDocument()
  })
})
