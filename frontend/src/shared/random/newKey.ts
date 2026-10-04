/**
 * A fresh random key: 32 hex characters, like a UUID without dashes.
 *
 * `crypto.randomUUID` exists only on secure pages (https, or the booth PC's own 127.0.0.1). A TV
 * opens the booth over plain http on the Wi-Fi, where only `crypto.getRandomValues` is there.
 */
export function newKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}
