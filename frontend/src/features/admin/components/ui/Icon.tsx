/** Small line icons for compact admin controls. Always paired with an accessible label. */

const PATHS = {
  details: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-10v6m0-9.5v.5',
  preview: 'M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z',
  rename: 'M4 20h4L19 9l-4-4L4 16v4Zm9-13 4 4',
  replace: 'M4 12a8 8 0 0 1 14-5.3M20 4v4h-4M20 12a8 8 0 0 1-14 5.3M4 20v-4h4',
  delete: 'M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13M10 11v6m4-6v6',
  up: 'm6 15 6-6 6 6',
  down: 'm6 9 6 6 6-6',
  swap: 'M7 4v16m0 0-3-3m3 3 3-3M17 20V4m0 0-3 3m3-3 3 3',
  check: 'm5 12 5 5 9-10',
  success: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-4-9 3 3 5-6',
  warning: 'M12 3 2 20h20L12 3Zm0 6v5m0 3v.5',
  error: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM9 9l6 6m0-6-6 6',
  close: 'm6 6 12 12M18 6 6 18',
  plus: 'M12 5v14M5 12h14',
  download: 'M12 4v11m0 0-4-4m4 4 4-4M5 20h14',
} as const

export type IconName = keyof typeof PATHS

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
