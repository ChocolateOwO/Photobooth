import type { ButtonHTMLAttributes } from 'react'

import styles from './BigButton.module.css'

/** Touch-friendly button (at least 64 px). Pointer events cover touch, mouse and pen. */
export function BigButton({ className, type, ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      type={type === 'submit' || type === 'reset' ? type : 'button'}
      className={className ? `${styles.button} ${className}` : styles.button}
    />
  )
}
