import { createBrowserRouter } from 'react-router'

import { SystemHomePage } from '../features/system/SystemHomePage'
import { buildInstance } from '../shared/config/instance'

export const router = createBrowserRouter([
  { path: '/', element: <SystemHomePage instance={buildInstance} /> },
  { path: '*', element: <SystemHomePage instance={buildInstance} /> },
])
