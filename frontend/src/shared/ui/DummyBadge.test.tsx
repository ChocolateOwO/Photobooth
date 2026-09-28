import { act, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { App } from '../../app/App'
import { createApiClient } from '../api/client'
import { buildInstance } from '../config/instance'
import { DummyBadge } from './DummyBadge'
import { enterImmersive } from './immersive'

const neverCalled = createApiClient(async () => {
  throw new Error('no network in this test')
})

describe('DummyBadge', () => {
  it('is visible for the dummy instance', () => {
    render(<DummyBadge instance="dummy" />)
    expect(screen.getByTestId('dummy-badge')).toHaveTextContent('DUMMY')
  })

  it('is not rendered for main', () => {
    render(<DummyBadge instance="main" />)
    expect(screen.queryByTestId('dummy-badge')).not.toBeInTheDocument()
  })

  it('is rendered by the App shell regardless of page content', () => {
    render(
      <App instance="dummy" apiClient={neverCalled}>
        <p>any page</p>
      </App>,
    )
    expect(screen.getByTestId('dummy-badge')).toBeVisible()
  })

  it('steps aside while a booth screen owns the display, and comes back after it', () => {
    render(<DummyBadge instance="dummy" />)
    expect(screen.getByTestId('dummy-badge')).toBeInTheDocument()
    let leave: (() => void) | null = null
    act(() => {
      leave = enterImmersive()
    })
    expect(screen.queryByTestId('dummy-badge')).toBeNull()
    act(() => (leave as unknown as () => void)())
    expect(screen.getByTestId('dummy-badge')).toBeInTheDocument()
  })

  it('defaults the build instance to dummy unless explicitly main', () => {
    expect(buildInstance).toBe('dummy')
  })
})
