import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'

import type { Frame, ProfileSettings, RetakeMode, TemplateSummary } from '../../../shared/api/adminClient'
import { useAdminApi } from '../../../shared/api/AdminApiContext'
import { EventMessage, EventScreen } from '../../../shared/eventUi/EventUi'
import { FrameCarousel } from '../../../shared/eventUi/FrameCarousel'
import { StartScreen } from '../../../shared/eventUi/StartScreen'
import { galleryFrames, offeredLayouts } from '../frameCatalog'
import { IconButton, PillGroup } from './ui/Controls'
import styles from './EventPreview.module.css'

type Mode = 'start' | 'frames'

interface EventPreviewProps {
  settings: ProfileSettings
  templates: TemplateSummary[]
  frames: Frame[] | undefined
}

interface ScreenSize {
  width: number
  height: number
}

/** Logical screen sizes the preview accepts (a phone up to a 4K display). */
const PREVIEW_LIMITS = { min: 320, max: 3840 } as const
const DEFAULT_PREVIEW_SIZE: ScreenSize = { width: 1080, height: 1920 }

const SIZE_PRESETS: (ScreenSize & { name: string })[] = [
  { name: 'Kiosk portrait', width: 1080, height: 1920 },
  { name: 'Kiosk landscape', width: 1920, height: 1080 },
  { name: 'Tablet', width: 1280, height: 800 },
  { name: 'Phone', width: 390, height: 844 },
]

const RETAKE_LABELS: Record<RetakeMode, string> = {
  none: 'No retakes',
  per_photo: 'Retake any single photo',
  all: 'Retake all photos',
}

function parseSide(text: string): number | null {
  if (!/^\d+$/.test(text.trim())) return null
  const value = Number(text)
  return value >= PREVIEW_LIMITS.min && value <= PREVIEW_LIMITS.max ? value : null
}

/**
 * Draws its children at a logical screen size and scales them down (never up) to fit the space
 * it is given, so the whole screen is always visible and nothing needs a scrollbar.
 */
function ScaledScreen({ size, children }: { size: ScreenSize; children: ReactNode }) {
  const stageRef = useRef<HTMLDivElement>(null)
  const [room, setRoom] = useState<ScreenSize | null>(null)

  useLayoutEffect(() => {
    const stage = stageRef.current
    if (!stage || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect
      if (box) setRoom({ width: box.width, height: box.height })
    })
    observer.observe(stage)
    return () => observer.disconnect()
  }, [])

  const scale = room ? Math.min(1, room.width / size.width, room.height / size.height) : 1
  const stageStyle = { '--preview-ratio': `${size.width} / ${size.height}` } as CSSProperties
  return (
    <div ref={stageRef} className={styles.stage} style={stageStyle}>
      <div
        className={styles.scaled}
        style={{ width: size.width * scale, height: size.height * scale }}
        data-testid="preview-screen"
        data-scale={scale.toFixed(4)}
      >
        <div
          className={styles.logical}
          style={{ width: size.width, height: size.height, transform: `scale(${scale})` }}
          data-testid="preview-viewport"
          data-width={size.width}
          data-height={size.height}
        >
          {children}
        </div>
      </div>
    </div>
  )
}

/** The participant screens exactly as the booth draws them, from the draft settings. */
function PreviewScreen({ settings, templates, frames, mode }: EventPreviewProps & { mode: Mode }) {
  const api = useAdminApi()
  // The participant gallery itself, with this draft's frames and order (a local choice only).
  const [chosen, setChosen] = useState<string | null>(null)
  const backgroundUrl = settings.background_asset_id
    ? api.assetContentUrl(settings.background_asset_id)
    : null
  const logoUrl = settings.logo_asset_id ? api.assetContentUrl(settings.logo_asset_id) : null

  if (mode === 'start') {
    return (
      <StartScreen
        tokens={settings.theme.tokens}
        backgroundImageUrl={backgroundUrl}
        logoUrl={logoUrl}
        startText={settings.start_button_text}
        label="Start screen preview"
        inert
      />
    )
  }

  const offered = galleryFrames(settings.enabled_layouts, frames ?? [], templates, (frame) =>
    api.framePreviewUrl(frame.id, 1, frame.sha256),
  )
  return (
    <EventScreen
      tokens={settings.theme.tokens}
      backgroundImageUrl={backgroundUrl}
      className={styles.galleryScreen}
      label="Frame selection preview"
    >
      {offered.length === 0 ? (
        <div className={styles.emptyGallery}>
          <EventMessage kind="info">No frames are available to participants yet.</EventMessage>
        </div>
      ) : (
        <FrameCarousel
          compact
          frames={offered}
          allowSurprise={settings.allow_surprise_me}
          selectedId={chosen}
          onConfirm={(frame) => setChosen(frame.id)}
          onStart={() => undefined}
          onChooseAgain={() => setChosen(null)}
        />
      )}
    </EventScreen>
  )
}

export function EventPreview({ settings, templates, frames }: EventPreviewProps) {
  const [mode, setMode] = useState<Mode>('start')
  const [size, setSize] = useState<ScreenSize>(DEFAULT_PREVIEW_SIZE)
  const [draft, setDraft] = useState({
    width: String(DEFAULT_PREVIEW_SIZE.width),
    height: String(DEFAULT_PREVIEW_SIZE.height),
  })
  const widthOk = parseSide(draft.width) !== null
  const heightOk = parseSide(draft.height) !== null
  const orientation = size.height >= size.width ? 'portrait' : 'landscape'

  const apply = (next: ScreenSize) => {
    setSize(next)
    setDraft({ width: String(next.width), height: String(next.height) })
  }
  const edit = (side: 'width' | 'height', text: string) => {
    const nextDraft = { ...draft, [side]: text }
    setDraft(nextDraft)
    const value = parseSide(text)
    // An invalid value is only shown with its message; the preview keeps the last good size.
    if (value !== null) setSize((current) => ({ ...current, [side]: value }))
  }
  const swap = () => apply({ width: size.height, height: size.width })

  const retakeText = RETAKE_LABELS[settings.retake_mode]
  const layoutNames = offeredLayouts(settings.enabled_layouts, frames ?? [], templates).map(
    (key) => templates.find((t) => t.key === key)?.name ?? key,
  )
  const sizeError = `Enter a whole number from ${PREVIEW_LIMITS.min} to ${PREVIEW_LIMITS.max} px.`

  return (
    <section aria-label="Event preview" data-testid="preparation-preview" className={styles.previewSection}>
      <div className={styles.previewTop}>
        <h2 className={styles.previewHeading}>Preview</h2>
        <PillGroup
          label="Preview screen"
          options={[
            { value: 'start', label: 'Start screen' },
            { value: 'frames', label: 'Frame selection' },
          ]}
          value={mode}
          onChange={(value) => setMode(value as Mode)}
        />
        <select
          className={styles.presetSelect}
          aria-label="Common screen sizes"
          value={SIZE_PRESETS.find((p) => p.width === size.width && p.height === size.height)?.name ?? ''}
          onChange={(e) => {
            const preset = SIZE_PRESETS.find((p) => p.name === e.target.value)
            if (preset) apply(preset)
          }}
        >
          <option value="" disabled>
            Custom size
          </option>
          {SIZE_PRESETS.map((preset) => (
            <option key={preset.name} value={preset.name}>
              {preset.name} ({preset.width} × {preset.height})
            </option>
          ))}
        </select>
      </div>

      <div className={styles.sizeControls} role="group" aria-label="Preview screen size">
        <label className={styles.sizeField}>
          <span>Width</span>
          <input
            type="number"
            inputMode="numeric"
            min={PREVIEW_LIMITS.min}
            max={PREVIEW_LIMITS.max}
            value={draft.width}
            aria-label="Preview width in pixels"
            aria-invalid={!widthOk}
            aria-describedby={!widthOk ? 'preview-size-error' : undefined}
            onChange={(e) => edit('width', e.target.value)}
            onBlur={() => !widthOk && setDraft((d) => ({ ...d, width: String(size.width) }))}
          />
        </label>
        <IconButton icon="swap" label="Swap width and height" onClick={swap} />
        <label className={styles.sizeField}>
          <span>Height</span>
          <input
            type="number"
            inputMode="numeric"
            min={PREVIEW_LIMITS.min}
            max={PREVIEW_LIMITS.max}
            value={draft.height}
            aria-label="Preview height in pixels"
            aria-invalid={!heightOk}
            aria-describedby={!heightOk ? 'preview-size-error' : undefined}
            onChange={(e) => edit('height', e.target.value)}
            onBlur={() => !heightOk && setDraft((d) => ({ ...d, height: String(size.height) }))}
          />
        </label>
        <PillGroup
          label="Orientation"
          options={[
            { value: 'portrait', label: 'Portrait' },
            { value: 'landscape', label: 'Landscape' },
          ]}
          value={orientation}
          onChange={(value) => {
            if (value !== orientation) swap()
          }}
        />
        <span className={styles.sizeText} data-testid="preview-size" aria-live="polite">
          {size.width} × {size.height} px
        </span>
      </div>      {(!widthOk || !heightOk) && (
        <p id="preview-size-error" role="alert" className={styles.sizeError}>
          {sizeError} The preview keeps {size.width} × {size.height} px.
        </p>
      )}

      <div data-testid="event-preview" className={styles.screenBox}>
        <ScaledScreen size={size}>
          <PreviewScreen settings={settings} templates={templates} frames={frames} mode={mode} />
        </ScaledScreen>
      </div>
      <p className={styles.caption}>
        <span>{settings.mirror ? 'Mirror: on' : 'Mirror: off'}</span>,{' '}
        <span>Timeout: {settings.inactivity_timeout_s} s</span>, <span>{retakeText}</span>
        {layoutNames.length > 0 && <span>. Layouts offered: {layoutNames.join(', ')}</span>}
        <span>. Countdown: {Number.isInteger(settings.countdown_seconds) ? settings.countdown_seconds : '?'} s</span>
      </p>
    </section>
  )
}
