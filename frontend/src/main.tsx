import './shared/theme/tokens.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router'

import { App } from './app/App'
import { router } from './app/router'
import { buildInstance } from './shared/config/instance'

const root = document.getElementById('root')
if (root === null) {
  throw new Error('root element missing')
}

createRoot(root).render(
  <StrictMode>
    <App instance={buildInstance}>
      <RouterProvider router={router} />
    </App>
  </StrictMode>,
)
