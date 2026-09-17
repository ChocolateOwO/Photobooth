import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach } from 'vitest'

// The kiosk dev machine can be slow to render under load; wait longer for async UI updates.
// This changes only how long findBy*/waitFor poll, never what the assertions require.
configure({ asyncUtilTimeout: 10_000 })

afterEach(() => {
  cleanup()
})
