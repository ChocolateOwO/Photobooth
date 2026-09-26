import './shared/theme/tokens.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router'

import { App } from './app/App'
import { router } from './app/router'
import { createAdminApiClient } from './shared/api/adminClient'
import { createApiClient } from './shared/api/client'
import { captureDeviceKeyFromFragment, createStorageDeviceKeyStore } from './shared/api/deviceKey'
import { rememberCameraPreference } from './shared/camera/camera'
import { buildInstance } from './shared/config/instance'

const root = document.getElementById('root')
if (root === null) {
  throw new Error('root element missing')
}

// Capture the pairing device key before anything else can read or log the URL.
const deviceKeys = createStorageDeviceKeyStore(buildInstance)
captureDeviceKeyFromFragment(window.location, window.history, deviceKeys)
// `?camera=test` (Dummy only) is noted now: the photo screen is reached long after this address.
if (buildInstance === 'dummy') {
  rememberCameraPreference()
}
const apiClient = createApiClient(undefined, deviceKeys)
const adminClient = createAdminApiClient(undefined, deviceKeys)

createRoot(root).render(
  <StrictMode>
    <App instance={buildInstance} apiClient={apiClient} adminClient={adminClient}>
      <RouterProvider router={router} />
    </App>
  </StrictMode>,
)
