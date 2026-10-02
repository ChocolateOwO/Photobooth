import { useId } from 'react'

import type { DecorateOutput, DecorationFilter } from '../../shared/api/client'
import { matrixValues } from './colorMatrix'
import styles from './FilterSwatch.module.css'

/**
 * The guest's first photo with one filter on it, so each filter button shows what it does to
 * their own picture. Cropped and mirrored as the finished photo has it; the colour matrix is the
 * very one the server applies.
 */

interface FilterSwatchProps {
  output: DecorateOutput
  mirror: boolean
  photoUrl: (captureId: string, version: string | null) => string
  filter: DecorationFilter
}

export function FilterSwatch({ output, mirror, photoUrl, filter }: FilterSwatchProps) {
  const id = useId().replaceAll(':', '')
  const slot = output.slots[0]
  if (!slot) return null
  const filterOn = filter.key !== 'none'
  return (
    <svg
      className={styles.swatch}
      viewBox={`${slot.x} ${slot.y} ${slot.width} ${slot.height}`}
      aria-hidden="true"
      data-testid="filter-swatch"
    >
      {filterOn && (
        <defs>
          <filter id={`${id}-f`} colorInterpolationFilters="sRGB" x="0" y="0" width="1" height="1">
            <feColorMatrix type="matrix" values={matrixValues(filter.matrix)} />
          </filter>
        </defs>
      )}
      <image
        href={photoUrl(slot.capture_id, slot.version)}
        x={slot.x}
        y={slot.y}
        width={slot.width}
        height={slot.height}
        preserveAspectRatio="xMidYMid slice"
        filter={filterOn ? `url(#${id}-f)` : undefined}
        transform={mirror ? `translate(${2 * slot.x + slot.width} 0) scale(-1 1)` : undefined}
      />
    </svg>
  )
}
