import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { FakeAdminServer } from '../testing/fakeAdminServer'
import { renderAdmin } from '../testing/renderAdmin'

const EXAMPLES = {
  'Profile name': 'e.g. Chiang Mai Expo 2026',
  Title: 'e.g. Get ready for your photo!',
  Subtitle: 'e.g. Look at the camera and strike a pose.',
  'Start button text': 'e.g. Start taking photos',
  'Inactivity timeout (seconds)': 'e.g. 120',
} as const

function signedInServer() {
  const server = new FakeAdminServer()
  server.signedIn = true
  return server
}

describe('placeholder and helper text', () => {
  it('shows example text only as placeholders next to visible labels', async () => {
    renderAdmin('/admin/profiles/new', { server: signedInServer() })
    await screen.findByLabelText('Profile name')
    for (const [label, example] of Object.entries(EXAMPLES)) {
      const field = screen.getByLabelText(label) // the visible label still names the field
      expect(field).toHaveAttribute('placeholder', example)
      expect(field).not.toHaveValue(example)
    }
    expect(screen.getByLabelText('Profile name')).toHaveValue('')
    expect(screen.getByLabelText('Title')).toHaveValue('')
    expect(screen.getByLabelText('Subtitle')).toHaveValue('')
  })

  it('lets typing replace the example and shows the example again when cleared', async () => {
    renderAdmin('/admin/profiles/new', { server: signedInServer() })
    const start = await screen.findByLabelText('Start button text')
    await userEvent.clear(start)
    expect(start).toHaveValue('') // empty: the browser now shows the grey example

    await userEvent.type(start, 'Go')
    expect(start).toHaveValue('Go')
    expect(start).toHaveAttribute('placeholder', EXAMPLES['Start button text'])

    const timeout = screen.getByLabelText('Inactivity timeout (seconds)')
    await userEvent.clear(timeout)
    expect(timeout).toHaveValue(null) // empty number field, so "e.g. 120" is visible
    await userEvent.type(timeout, '90')
    expect(timeout).toHaveValue(90)
  })

  it('never saves or previews example text as profile content', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await userEvent.type(await screen.findByLabelText('Profile name'), 'Real name')
    await userEvent.type(screen.getByLabelText('Title'), 'Real title')

    const preview = screen.getByTestId('preparation-preview')
    for (const example of Object.values(EXAMPLES)) {
      expect(within(preview).queryByText(example)).toBeNull()
    }

    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(server.profiles.size).toBe(1))
    const saved = [...server.profiles.values()][0]?.settings
    expect(saved?.subtitle).toBe('')
    const savedText = JSON.stringify(saved)
    for (const example of Object.values(EXAMPLES)) {
      expect(savedText).not.toContain(example)
    }
  })

  it('still requires real values when fields only show examples', async () => {
    const server = signedInServer()
    renderAdmin('/admin/profiles/new', { server })
    await userEvent.clear(await screen.findByLabelText('Inactivity timeout (seconds)'))
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    const text =
      (await screen.findByRole('alertdialog', { name: 'Some information is missing or invalid' })).textContent ?? ''
    expect(text).toContain('Profile name is required.')
    expect(text).toContain('Title is required.')
    expect(text).toContain('Inactivity timeout must be between 30 and 900 seconds.')
    expect(server.profiles.size).toBe(0)
  })

  it('connects short helper text to the settings placeholders can not explain', async () => {
    renderAdmin('/admin/profiles/new', { server: signedInServer() })
    expect(await screen.findByLabelText('Profile name')).toHaveAccessibleDescription(
      'Only admins see this name. It helps you find the profile later.',
    )
    expect(screen.getByLabelText('Inactivity timeout (seconds)')).toHaveAccessibleDescription(
      'After this many seconds without a touch, the booth goes back to the start screen (30–900).',
    )
    expect(screen.getByRole('group', { name: 'Retakes' })).toHaveAccessibleDescription(
      'Choose whether guests may redo photos before their result is made.',
    )
    expect(screen.getByRole('checkbox', { name: 'Mirror the camera preview' })).toHaveAccessibleDescription(
      'When on, the live camera preview works like a mirror.',
    )
    expect(screen.getByLabelText('Main button')).toHaveAccessibleDescription(
      'The main action, e.g. Start.',
    )
    expect(screen.getByLabelText('Logo image')).toHaveAccessibleDescription(
      'PNG or JPEG, up to 5 MB. A transparent PNG works best.',
    )
    expect(screen.getByLabelText('Background image')).toHaveAccessibleDescription(
      'PNG or JPEG, up to 12 MB. A 16:9 image fills the screen best.',
    )
  })

  it('adds examples to the sign-in form without replacing its labels', async () => {
    renderAdmin('/admin')
    expect(await screen.findByLabelText('Username')).toHaveAttribute('placeholder', 'Your admin username')
    expect(screen.getByLabelText('Password')).toHaveAttribute('placeholder', 'Your admin password')
    expect(screen.getByLabelText('Username')).toHaveValue('')
  })
})
