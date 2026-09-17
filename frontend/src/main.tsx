import './shared/theme/tokens.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router'

import { App } from './app/App'
import { router } from './app/router'
import { createApiClient } from './shared/api/client'
import { captureDeviceKeyFromFragment, createStorageDeviceKeyStore } from './shared/api/deviceKey'
import { buildInstance } from './shared/config/instance'

const root = document.getElementById('root')
if (root === null) {
  throw new Error('root element missing')
}

// Capture the pairing device key before anything else can read or log the URL.
const deviceKeys = createStorageDeviceKeyStore(buildInstance)
captureDeviceKeyFromFragment(window.location, window.history, deviceKeys)
const apiClient = createApiClient(undefined, deviceKeys)

createRoot(root).render(
  <StrictMode>
    <App instance={buildInstance} apiClient={apiClient}>
      <RouterProvider router={router} />
    </App>
  </StrictMode>,
)
