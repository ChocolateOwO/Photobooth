import { createBrowserRouter, Outlet } from 'react-router'

import { AdminAuthProvider } from '../features/admin/api/AdminAuthProvider'
import { ActivityPage } from '../features/admin/pages/ActivityPage'
import { AdminGate } from '../features/admin/pages/AdminGate'
import { BoothTestPage } from '../features/admin/pages/BoothTestPage'
import { FrameManagerPage } from '../features/admin/pages/FrameManagerPage'
import { HistoryPage } from '../features/admin/pages/HistoryPage'
import { ProfileEditorPage } from '../features/admin/pages/ProfileEditorPage'
import { ProfileListPage } from '../features/admin/pages/ProfileListPage'
import { RetentionPage } from '../features/admin/pages/RetentionPage'
import { StatisticsPage } from '../features/admin/pages/StatisticsPage'
import { SystemPage } from '../features/admin/pages/SystemPage'
import { BoothErrorBoundary } from '../features/booth/BoothSafety'
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
      { path: 'history', element: <HistoryPage /> },
      { path: 'statistics', element: <StatisticsPage /> },
      { path: 'activity', element: <ActivityPage /> },
      { path: 'retention', element: <RetentionPage /> },
      { path: 'system', element: <SystemPage /> },
    ],
  },
  // Every booth screen: a screen that fails never leaves the booth blank.
  { path: '/booth', element: <BoothErrorBoundary><BoothStartPage /></BoothErrorBoundary> },
  { path: '/booth/frames', element: <BoothErrorBoundary><FrameSelectPage /></BoothErrorBoundary> },
  { path: '/booth/capture', element: <BoothErrorBoundary><CapturePage /></BoothErrorBoundary> },
  { path: '/booth/decorate', element: <BoothErrorBoundary><DecoratePage /></BoothErrorBoundary> },
  { path: '/booth/done', element: <BoothErrorBoundary><DeliveryPage /></BoothErrorBoundary> },
  { path: '*', element: <SystemHomePage instance={buildInstance} /> },
]

export const router = createBrowserRouter(routes)