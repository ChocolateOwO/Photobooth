import { useState, type FormEvent, type ReactNode } from 'react'

import { AdminApiError } from '../../../shared/api/adminClient'
import { BigButton } from '../../../shared/ui/BigButton'
import { useAdminAuth } from '../api/AdminAuthProvider'
import { AdminLayout } from '../components/AdminLayout'
import styles from './AdminGate.module.css'

export function AdminGate({ children }: { children: ReactNode }) {
  const { status, username, login, logout, recheck } = useAdminAuth()

  const [usernameInput, setUsernameInput] = useState('')
  const [passwordInput, setPasswordInput] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const handleSignIn = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setErrorMessage(null)
    setIsSubmitting(true)

    try {
      await login(usernameInput, passwordInput)
    } catch (err: unknown) {
      setPasswordInput('')
      if (err instanceof AdminApiError) {
        if (err.kind === 'throttled') {
          const seconds = err.retryAfterSeconds ?? 60
          setErrorMessage(`Too many attempts. Try again in ${seconds} seconds.`)
        } else if (err.kind === 'unauthenticated') {
          setErrorMessage('Wrong username or password.')
        } else {
          setErrorMessage(err.messages[0] ?? err.message)
        }
      } else if (err instanceof Error) {
        setErrorMessage(err.message)
      } else {
        setErrorMessage('Sign in failed.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  if (status === 'checking') {
    return (
      <div className={styles.centeredContainer}>
        <p className={styles.text}>Checking admin session…</p>
      </div>
    )
  }

  if (status === 'not-paired') {
    return (
      <div className={styles.centeredContainer}>
        <div className={styles.card}>
          <h1 className={styles.heading}>Kiosk not paired</h1>
          <p className={styles.text}>
            Pair this browser from the booth computer: run scripts\run-dummy.ps1 -PairOnly, then reload.
          </p>
          <BigButton type="button" onClick={recheck}>
            Check again
          </BigButton>
        </div>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className={styles.centeredContainer}>
        <div className={styles.card}>
          <div role="alert" className={styles.alert}>
            The kiosk server could not be reached.
          </div>
          <BigButton type="button" onClick={recheck}>
            Check again
          </BigButton>
        </div>
      </div>
    )
  }

  if (status === 'signed-out' || status === 'expired') {
    return (
      <div className={styles.centeredContainer}>
        <div className={styles.card}>
          <h1 className={styles.heading}>Admin sign in</h1>
          {status === 'expired' && (
            <div role="alert" className={styles.alert}>
              Your session expired. Sign in again.
            </div>
          )}
          {errorMessage && (
            <div role="alert" className={styles.alert}>
              {errorMessage}
            </div>
          )}
          <form onSubmit={handleSignIn} className={styles.form}>
            <div className={styles.field}>
              <label htmlFor="admin-username" className={styles.label}>
                Username
              </label>
              <input
                id="admin-username"
                name="username"
                type="text"
                autoComplete="username"
                value={usernameInput}
                onChange={(e) => setUsernameInput(e.target.value)}
                className={styles.input}
                required
              />
            </div>
            <div className={styles.field}>
              <label htmlFor="admin-password" className={styles.label}>
                Password
              </label>
              <input
                id="admin-password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={passwordInput}
                onChange={(e) => setPasswordInput(e.target.value)}
                className={styles.input}
                required
              />
            </div>
            <BigButton type="submit" disabled={isSubmitting} className={styles.submitButton}>
              Sign in
            </BigButton>
          </form>
        </div>
      </div>
    )
  }

  return (
    <AdminLayout username={username} onLogout={logout}>
      {children}
    </AdminLayout>
  )
}