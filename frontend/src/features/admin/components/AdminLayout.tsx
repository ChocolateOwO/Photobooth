import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import styles from './AdminLayout.module.css'

interface AdminLayoutProps {
  username: string | null
  onLogout: () => Promise<void>
  children: ReactNode
}

export function AdminLayout({ username, onLogout, children }: AdminLayoutProps) {
  const [signingOut, setSigningOut] = useState(false)
  const [logoutFailed, setLogoutFailed] = useState(false)

  const handleLogout = async () => {
    setSigningOut(true)
    setLogoutFailed(false)
    try {
      await onLogout()
    } catch {
      // The server session may still be valid: say so and keep admin data hidden.
      setLogoutFailed(true)
    } finally {
      setSigningOut(false)
    }
  }

  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <div className={styles.userSection}>Signed in as {username ?? ''}</div>
        <nav className={styles.nav}>
          <Link to="/admin" className={styles.navLink}>
            Event Profiles
          </Link>
          <Link to="/admin/frames" className={styles.navLink}>
            Frames
          </Link>
          <Link to="/admin/test" className={styles.navLink}>
            Test booth
          </Link>
        </nav>
        <button
          type="button"
          disabled={signingOut}
          onClick={() => {
            void handleLogout()
          }}
          className={styles.signOutButton}
        >
          {logoutFailed ? 'Try sign out again' : 'Sign out'}
        </button>
      </header>
      <main className={styles.main}>
        {logoutFailed ? (
          <div role="alert" className={styles.logoutAlert}>
            Sign-out did not finish, so this admin session may still be active. Check the kiosk server,
            then press Try sign out again.
          </div>
        ) : (
          children
        )}
      </main>
    </div>
  )
}