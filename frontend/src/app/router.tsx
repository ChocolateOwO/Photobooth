import { createBrowserRouter, Outlet } from 'react-router'

import { AdminAuthProvider } from '../features/admin/api/AdminAuthProvider'
import { AdminGate } from '../features/admin/pages/AdminGate'
import { BoothTestPage } from '../features/admin/pages/BoothTestPage'
import { FrameManagerPage } from '../features/admin/pages/FrameManagerPage'
import { ProfileEditorPage } from '../features/admin/pages/ProfileEditorPage'
import { ProfileListPage } from '../features/admin/pages/ProfileListPage'
import { BoothStartPage } from '../features/booth/BoothStartPage'
import { CapturePage } from '../features/booth/CapturePage'
import { DecoratePage } from '../features/booth/DecoratePage'
import { DeliveryPage } from '../features/booth/DeliveryPage'
import { FrameSelectPage } from '../features/booth/FrameSelectPage'
import { SystemHomePage } from '../features/system/SystemHomePage'
import { buildInstance } from '../shared/config/instance'

export const routes = [
  { path: '/', element: <SystemHomePage instance={buildInstance} /> },
  {
    path: '/admin',
    element: (
      <AdminAuthProvider>
        <AdminGate>
          <Outlet />
        </AdminGate>
      </AdminAuthProvider>
    ),
    children: [
      { index: true, element: <ProfileListPage /> },
      { path: 'profiles/new', element: <ProfileEditorPage /> },
      { path: 'profiles/:profileId', element: <ProfileEditorPage /> },
      { path: 'frames', element: <FrameManagerPage /> },
      { path: 'test', element: <BoothTestPage /> },
    ],
  },
  { path: '/booth', element: <BoothStartPage /> },
  { path: '/booth/frames', element: <FrameSelectPage /> },
  { path: '/booth/capture', element: <CapturePage /> },
  { path: '/booth/decorate', element: <DecoratePage /> },
  { path: '/booth/done', element: <DeliveryPage /> },
  { path: '*', element: <SystemHomePage instance={buildInstance} /> },
]

export const router = createBrowserRouter(routes)