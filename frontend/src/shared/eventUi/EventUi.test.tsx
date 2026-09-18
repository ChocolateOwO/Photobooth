import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { THEME_CATALOG } from '../../features/admin/testing/themeCatalog.fixture'
import { themeStyle, tokenVar } from '../eventTheme/theme'
import {
  EventButton,
  EventCard,
  EventHeading,
  EventInput,
  EventMessage,
  EventScreen,
  EventText,
} from './EventUi'

describe('event UI components', () => {
  it('sets the tokens only on the event screen, never on the page around it', () => {
    const tokens = THEME_CATALOG.presets[0]?.tokens ?? {}
    render(
      <div data-testid="admin-shell">
        <EventScreen tokens={tokens} label="Event">
          <EventHeading>Hello</EventHeading>
          <EventText>Body</EventText>
          <EventText muted>Hint</EventText>
          <EventButton>Start</EventButton>
          <EventButton variant="secondary" disabled>
            Back
          </EventButton>
          <EventInput id="i" label="Email" placeholder="name@example.com" />
          <EventCard>Card</EventCard>
          <EventMessage kind="warning">Careful</EventMessage>
        </EventScreen>
      </div>,
    )
    const screenEl = screen.getByRole('group', { name: 'Event' })
    for (const [key, value] of Object.entries(tokens)) {
      expect(screenEl.style.getPropertyValue(tokenVar(key))).toBe(value)
    }
    expect(screen.getByTestId('admin-shell').getAttribute('style')).toBeNull()
    expect(document.documentElement.style.getPropertyValue('--ev-background')).toBe('')
    expect(screen.getByRole('button', { name: 'Back' })).toBeDisabled()
    expect(screen.getByLabelText('Email')).toHaveAttribute('placeholder', 'name@example.com')
    expect(Object.keys(themeStyle(tokens))).toHaveLength(THEME_CATALOG.tokens.length)
  })
})
