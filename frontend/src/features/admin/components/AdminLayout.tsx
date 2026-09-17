import type { ReactNode } from 'react'
import { Link } from 'react-router'

import styles from './AdminLayout.module.css'

interface AdminLayoutProps {
  username: string | null
  onLogout: () => void | Promise<void>
  children: ReactNode
}

export function AdminLayout({ username, onLogout, children }: AdminLayoutProps) {
  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <div className={styles.userSection}>
          Signed in as {username ?? ''}
        </div>
        <nav className={styles.nav}>
          <Link to="/admin" className={styles.navLink}>
            Event Profiles
          </Link>
        </nav>
        <button
          type="button"
          onClick={() => {
            void onLogout()
          }}
          className={styles.signOutButton}
        >
          Sign out
        </button>
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  )
}
