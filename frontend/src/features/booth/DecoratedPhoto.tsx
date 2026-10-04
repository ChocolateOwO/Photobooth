import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react'

import type { DecorateOutput, DecorationFilter, StickerOffer } from '../../shared/api/client'
import { matrixValues } from './colorMatrix'
import type { PlacedSticker } from './decorationEditor'
import { follow, handleSpots, resizeFrom, type HandleKind, type Point } from './stickerGesture'
import styles from './DecoratedPhoto.module.css'

/**
 * One finished photo as it will be made, drawn the way the server draws it.
 *
 * The same order and the same numbers as the server's renderer: the photos cover their slots
 * (centred, mirrored when the event mirrors), the filter's colour matrix colours the photos only,
 * the organizer's frame lies on top unchanged, and the stickers lie on the frame in the order
 * they were added. Everything is in the photo's own pixels (the SVG viewBox), so the preview
 * matches the 300-DPI result at any screen size.
 *
 * The chosen sticker carries its own controls while the guest decorates: a compact outline and
 * three round handles on its corners (Move, Resize, Remove), the same size on screen whatever size
 * the photo is shown at, and kept on the photo near its edges. They belong to the screen only:
 * they are never drawn while the decoration is frozen for confirmation, never on a picture-only
 * photo, and never sent to the server (the server renders from the decoration's numbers alone).
 */

/** The handles' radius on screen, in CSS pixels (a 48-pixel touch target). */
export const HANDLE_RADIUS_PX = 24

const HANDLE_LABELS: Record<HandleKind, string> = {
  move: 'Move sticker',
  resize: 'Resize sticker',
  remove: 'Remove sticker',
}

/** Icons on a 2 by 2 square around the handle's centre. */
const HANDLE_ICONS: Record<HandleKind, string> = {
  move:
    'M0 -0.8 L0 0.8 M-0.8 0 L0.8 0 M-0.25 -0.55 L0 -0.8 L0.25 -0.55 M-0.25 0.55 L0 0.8 L0.25 0.55 ' +
    'M-0.55 -0.25 L-0.8 0 L-0.55 0.25 M0.55 -0.25 L0.8 0 L0.55 0.25',
  resize: 'M-0.6 0.6 L0.6 -0.6 M0.1 -0.6 L0.6 -0.6 L0.6 -0.1 M-0.6 0.1 L-0.6 0.6 L-0.1 0.6',
  remove: 'M-0.5 -0.5 L0.5 0.5 M0.5 -0.5 L-0.5 0.5',
}

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
  /** Shown, not touched: a gesture under way is let go (the guest is asked to confirm). */
  frozen?: boolean
  /** Without these the photo is a picture only (a filter thumbnail, the review). */
  onSelect?: (id: number | null) => void
  onMove?: (sticker: PlacedSticker) => void
  onMoveEnd?: () => void
  /** The Remove handle: the chosen sticker goes (one undo step). */
  onRemove?: () => void
}

interface Gesture {
  /** drag moves (one finger) or pinches (two); esize scales about the sticker's centre. */
  mode: 'drag' | 'resize'
  /** Where the sticker was when the current fingers came down, and where it is now. */
  sticker: PlacedSticker
  latest: PlacedSticker
  pointers: Map<number, Point>
  from: Point[]
  /** The sticker's centre in photo pixels (for esize). */
  centre: Point
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
  frozen = false,
  onSelect,
  onMove,
  onMoveEnd,
  onRemove,
}: DecoratedPhotoProps) {
  const id = useId().replaceAll(':', '')
  const svgRef = useRef<SVGSVGElement>(null)
  const gesture = useRef<Gesture | null>(null)
  const { width: W, height: H } = output
  const interactive = Boolean(onSelect && onMove) && !frozen
  useEffect(() => {
    if (!interactive) gesture.current = null
  }, [interactive])
  // Photo pixels per screen pixel, so the handles keep their size on any screen.
  const [unit, setUnit] = useState(1)
  useLayoutEffect(() => {
    const svg = svgRef.current
    if (!svg) return undefined
    const measure = () => {
      const shown = svg.getBoundingClientRect().width
      setUnit(shown > 0 ? W / shown : 1)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(measure)
    observer.observe(svg)
    return () => observer.disconnect()
  }, [W])

  function toPhoto(event: ReactPointerEvent): Point {
    const svg = svgRef.current
    const matrix = typeof svg?.getScreenCTM === 'function' ? svg.getScreenCTM() : null
    if (!svg || !matrix) return { x: 0, y: 0 }
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse())
    return { x: point.x, y: point.y }
  }

  function begin(event: ReactPointerEvent, sticker: PlacedSticker) {
    if (!interactive) return
    event.stopPropagation()
    event.preventDefault()
    const current = gesture.current
    // A resize belongs to the one pointer on its handle: another finger meanwhile is ignored.
    if (current?.mode === 'resize') return
    svgRef.current?.setPointerCapture?.(event.pointerId)
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
      mode: 'drag',
      sticker,
      latest: sticker,
      pointers: new Map([[event.pointerId, at]]),
      from: [at],
      centre: { x: sticker.x * W, y: sticker.y * H },
    }
  }

  function beginResize(event: ReactPointerEvent, sticker: PlacedSticker) {
    if (!interactive) return
    event.stopPropagation()
    event.preventDefault()
    if (gesture.current) return // one gesture at a time
    svgRef.current?.setPointerCapture?.(event.pointerId)
    const at = toPhoto(event)
    gesture.current = {
      mode: 'resize',
      sticker,
      latest: sticker,
      pointers: new Map([[event.pointerId, at]]),
      from: [at],
      centre: { x: sticker.x * W, y: sticker.y * H },
    }
  }

  function remove(event: ReactPointerEvent | ReactKeyboardEvent) {
    if (!interactive) return
    event.stopPropagation()
    event.preventDefault()
    gesture.current = null
    onRemove?.()
  }

  function moving(event: ReactPointerEvent) {
    const current = gesture.current
    if (!current || !current.pointers.has(event.pointerId)) return
    const at = toPhoto(event)
    current.pointers.set(event.pointerId, at)
    if (current.mode === 'resize') {
      const from = current.from[0]
      current.latest = from ? resizeFrom(current.sticker, current.centre, from, at) : current.sticker
    } else {
      const to = [...current.pointers.values()]
      current.latest = follow(current.sticker, current.from, to, { width: W, height: H })
    }
    onMove?.(current.latest)
  }

  function end(event: ReactPointerEvent) {
    const current = gesture.current
    if (!current || !current.pointers.has(event.pointerId)) return
    current.pointers.delete(event.pointerId)
    if (current.mode === 'drag' && current.pointers.size > 0) {
      // One finger stays: it carries on moving the sticker from where it is now.
      current.sticker = current.latest
      current.from = [...current.pointers.values()]
      return
    }
    gesture.current = null
    onMoveEnd?.() // the whole gesture is one undo step
  }

  const filterOn = filter && filter.key !== 'none'
  const chosen = interactive ? stickers.find((placed) => placed.id === selected) : undefined
  const chosenArt = chosen ? art.get(chosen.sticker) : undefined
  const radius = HANDLE_RADIUS_PX * unit
  const spots =
    chosen && chosenArt
      ? handleSpots(chosen, chosenArt.height / chosenArt.width, { width: W, height: H }, radius)
      : null

  return (
    <svg
      ref={svgRef}
      className={styles.photo}
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={label}
      data-testid="decorated-photo"
      data-output={output.output_index}
      // A tap on the photo itself lets the sticker go, but never in the middle of a gesture.
      onPointerDown={interactive ? () => gesture.current === null && onSelect?.(null) : undefined}
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
            {placed.id === selected && interactive && (
              <rect
                className={styles.selection}
                x={-w / 2}
                y={-h / 2}
                width={w}
                height={h}
                vectorEffect="non-scaling-stroke"
                data-testid="sticker-outline"
              />
            )}
          </g>
        )
      })}
      {chosen && spots && (
        <g data-testid="sticker-handles">
          {(['move', 'resize', 'remove'] as const).map((kind) => (
            <g
              key={kind}
              role="button"
              tabIndex={kind === 'remove' ? 0 : -1}
              aria-label={HANDLE_LABELS[kind]}
              data-handle={kind}
              className={styles.handle}
              transform={`translate(${spots[kind].x} ${spots[kind].y})`}
              onPointerDown={
                kind === 'move'
                  ? (event) => begin(event, chosen)
                  : kind === 'resize'
                    ? (event) => beginResize(event, chosen)
                    : (event) => remove(event)
              }
              onKeyDown={
                kind === 'remove'
                  ? (event) => {
                      if (['Enter', ' ', 'Delete', 'Backspace'].includes(event.key)) remove(event)
                    }
                  : undefined
              }
            >
              <circle r={radius} className={styles.handleDisc} vectorEffect="non-scaling-stroke" />
              <path
                d={HANDLE_ICONS[kind]}
                transform={`scale(${radius * 0.62})`}
                className={styles.handleIcon}
                vectorEffect="non-scaling-stroke"
              />
            </g>
          ))}
        </g>
      )}
    </svg>
  )
}
