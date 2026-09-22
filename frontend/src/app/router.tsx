import { createBrowserRouter, Outlet } from 'react-router'

import { AdminAuthProvider } from '../features/admin/api/AdminAuthProvider'
import { AdminGate } from '../features/admin/pages/AdminGate'
import { FrameManagerPage } from '../features/admin/pages/FrameManagerPage'
import { ProfileEditorPage } from '../features/admin/pages/ProfileEditorPage'
import { ProfileListPage } from '../features/admin/pages/ProfileListPage'
import { BoothStartPage } from '../features/booth/BoothStartPage'
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
    ],
  },
  { path: '/booth', element: <BoothStartPage /> },
  { path: '/booth/frames', element: <FrameSelectPage /> },
  { path: '*', element: <SystemHomePage instance={buildInstance} /> },
]

export const router = createBrowserRouter(routes)