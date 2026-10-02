import { useId, useRef, type PointerEvent as ReactPointerEvent } from 'react'

import type { DecorateOutput, DecorationFilter, StickerOffer } from '../../shared/api/client'
import { matrixValues } from './colorMatrix'
import type { PlacedSticker } from './decorationEditor'
import { follow, type Point } from './stickerGesture'
import styles from './DecoratedPhoto.module.css'

/**
 * One finished photo as it will be made, drawn the way the server draws it.
 *
 * The same order and the same numbers as the server's renderer: the photos cover their slots
 * (centred, mirrored when the event mirrors), the filter's colour matrix colours the photos only,
 * the organizer's frame lies on top unchanged, and the stickers lie on the frame in the order
 * they were added. Everything is in the photo's own pixels (the SVG viewBox), so the preview
 * matches the 300-DPI result at any screen size.
 */

interface DecoratedPhotoProps {
  output: DecorateOutput
  mirror: boolean
  frameUrl: string
  photoUrl: (captureId: string, version: string | null) => string
  filter: DecorationFilter | undefined
  stickers: readonly PlacedSticker[]
  art: ReadonlyMap<string, StickerOffer>
  label: string
  selected?: number | null
  /** Without these the photo is a picture only (a filter thumbnail, the review). */
  onSelect?: (id: number | null) => void
  onMove?: (sticker: PlacedSticker) => void
  onMoveEnd?: () => void
}

interface Gesture {
  /** Where the sticker was when the current fingers came down, and where it is now. */
  sticker: PlacedSticker
  latest: PlacedSticker
  pointers: Map<number, Point>
  from: Point[]
}

export function DecoratedPhoto({
  output,
  mirror,
  frameUrl,
  photoUrl,
  filter,
  stickers,
  art,
  label,
  selected = null,
  onSelect,
  onMove,
  onMoveEnd,
}: DecoratedPhotoProps) {
  const id = useId().replaceAll(':', '')
  const svgRef = useRef<SVGSVGElement>(null)
  const gesture = useRef<Gesture | null>(null)
  const { width: W, height: H } = output
  const interactive = Boolean(onSelect && onMove)

  function toPhoto(event: ReactPointerEvent): Point {
    const svg = svgRef.current
    const matrix = svg?.getScreenCTM()
    if (!svg || !matrix) return { x: 0, y: 0 }
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse())
    return { x: point.x, y: point.y }
  }

  function begin(event: ReactPointerEvent, sticker: PlacedSticker) {
    if (!interactive) return
    event.stopPropagation()
    event.preventDefault()
    svgRef.current?.setPointerCapture?.(event.pointerId)
    const current = gesture.current
    if (current && current.sticker.id === sticker.id && current.pointers.size === 1) {
      // A second finger joins: the gesture goes on from here with both fingers.
      current.pointers.set(event.pointerId, toPhoto(event))
      current.sticker = current.latest
      current.from = [...current.pointers.values()]
      return
    }
    if (current) return // a third finger, or a finger on another sticker, is ignored
    onSelect?.(sticker.id)
    const at = toPhoto(event)
    gesture.current = {
      sticker,
      latest: sticker,
      pointers: new Map([[event.pointerId, at]]),
      from: [at],
    }
  }

  function moving(event: ReactPointerEvent) {
    const current = gesture.current
    if (!current || !current.pointers.has(event.pointerId)) return
    current.pointers.set(event.pointerId, toPhoto(event))
    const to = [...current.pointers.values()]
    current.latest = follow(current.sticker, current.from, to, { width: W, height: H })
    onMove?.(current.latest)
  }

  function end(event: ReactPointerEvent) {
    const current = gesture.current
    if (!current || !current.pointers.has(event.pointerId)) return
    current.pointers.delete(event.pointerId)
    if (current.pointers.size > 0) {
      // One finger stays: it carries on moving the sticker from where it is now.
      current.sticker = current.latest
      current.from = [...current.pointers.values()]
      return
    }
    gesture.current = null
    onMoveEnd?.() // the whole gesture is one undo step
  }

  const filterOn = filter && filter.key !== 'none'

  return (
    <svg
      ref={svgRef}
      className={styles.photo}
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={label}
      data-testid="decorated-photo"
      data-output={output.output_index}
      onPointerDown={interactive ? () => onSelect?.(null) : undefined}
      onPointerMove={interactive ? moving : undefined}
      onPointerUp={interactive ? end : undefined}
      onPointerCancel={interactive ? end : undefined}
    >
      <defs>
        {filterOn && (
          <filter
            id={`${id}-filter`}
            colorInterpolationFilters="sRGB"
            x="0"
            y="0"
            width="1"
            height="1"
          >
            <feColorMatrix type="matrix" values={matrixValues(filter.matrix)} />
          </filter>
        )}
        {output.slots.map((slot, index) => (
          <clipPath id={`${id}-slot-${index}`} key={index}>
            <rect x={slot.x} y={slot.y} width={slot.width} height={slot.height} />
          </clipPath>
        ))}
      </defs>
      <rect width={W} height={H} fill="#ffffff" />
      <g filter={filterOn ? `url(#${id}-filter)` : undefined}>
        {output.slots.map((slot, index) => (
          <g key={slot.capture_id} clipPath={`url(#${id}-slot-${index})`}>
            <image
              href={photoUrl(slot.capture_id, slot.version)}
              x={slot.x}
              y={slot.y}
              width={slot.width}
              height={slot.height}
              preserveAspectRatio="xMidYMid slice"
              transform={
                mirror ? `translate(${2 * slot.x + slot.width} 0) scale(-1 1)` : undefined
              }
            />
          </g>
        ))}
      </g>
      <image href={frameUrl} x={0} y={0} width={W} height={H} preserveAspectRatio="none" />
      {stickers.map((placed) => {
        const offer = art.get(placed.sticker)
        if (!offer) return null
        const w = placed.size * W
        const h = (w * offer.height) / offer.width
        return (
          <g
            key={placed.id}
            transform={`translate(${placed.x * W} ${placed.y * H}) rotate(${placed.rotation})`}
            className={interactive ? styles.sticker : undefined}
            data-testid="placed-sticker"
            data-sticker={placed.sticker}
            data-selected={placed.id === selected ? '' : undefined}
            onPointerDown={interactive ? (event) => begin(event, placed) : undefined}
          >
            <image
              href={offer.url}
              x={-w / 2}
              y={-h / 2}
              width={w}
              height={h}
              preserveAspectRatio="none"
            />
            {placed.id === selected && (
              <rect
                className={styles.selection}
                x={-w / 2 - 6}
                y={-h / 2 - 6}
                width={w + 12}
                height={h + 12}
                rx={12}
                vectorEffect="non-scaling-stroke"
              />
            )}
          </g>
        )
      })}
    </svg>
  )
}
