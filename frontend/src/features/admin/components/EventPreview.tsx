import { useState } from 'react'

import type { Frame, ProfileSettings, RetakeMode, TemplateSummary } from '../../../shared/api/adminClient'
import { useAdminApi } from '../../../shared/api/AdminApiContext'
import {
  EventButton,
  EventCard,
  EventHeading,
  EventInput,
  EventMessage,
  EventScreen,
  EventText,
} from '../../../shared/eventUi/EventUi'
import { FrameGallery } from '../../../shared/eventUi/FrameGallery'
import { galleryFrames, offeredLayouts } from '../frameCatalog'
import styles from './EventPreview.module.css'

type Mode = 'preparation' | 'frames'

interface EventPreviewProps {
  settings: ProfileSettings
  templates: TemplateSummary[]
  frames: Frame[] | undefined
}

const RETAKE_LABELS: Record<RetakeMode, string> = {
  none: 'No retakes',
  per_photo: 'Retake any single photo',
  all: 'Retake all photos',
}

interface ScreenProps extends EventPreviewProps {
  phone: boolean
  mode: Mode
}

/**
 * One event screen drawn only from the draft settings. Button labels such as "Back" and the
 * example messages are fixed booth wording, never profile content; admin hints stay outside.
 */
function PreviewScreen({ settings, templates, frames, phone, mode }: ScreenProps) {
  const api = useAdminApi()
  // The participant gallery itself, with this draft's frames and order (a local choice only).
  const [chosen, setChosen] = useState<string | null>(null)
  const backgroundUrl = settings.background_asset_id
    ? api.assetContentUrl(settings.background_asset_id)
    : null
  const logoUrl = settings.logo_asset_id ? api.assetContentUrl(settings.logo_asset_id) : null
  const offered = galleryFrames(settings.available_frames, frames ?? [], templates, (frame) =>
    api.framePreviewUrl(frame.id, 1, frame.sha256),
  )
  const prefix = phone ? 'phone' : 'wide'

  if (mode === 'frames') {
    return (
      <EventScreen
        tokens={settings.theme.tokens}
        backgroundImageUrl={backgroundUrl}
        className={phone ? styles.phoneScreen : styles.wideScreen}
        label={phone ? 'Phone-width frame selection preview' : 'Frame selection preview'}
      >
        {offered.length === 0 ? (
          <EventMessage kind="info">No frames are available to participants yet.</EventMessage>
        ) : (
          <FrameGallery
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

  return (
    <EventScreen
      tokens={settings.theme.tokens}
      backgroundImageUrl={backgroundUrl}
      className={phone ? styles.phoneScreen : styles.wideScreen}
      label={phone ? 'Phone-width preview' : 'Kiosk screen preview'}
    >
      <div className={phone ? styles.phoneGrid : styles.wideGrid}>
        <EventCard className={styles.welcome}>
          {logoUrl && <img src={logoUrl} alt="Preview logo" className={styles.logo} />}
          {settings.title && <EventHeading>{settings.title}</EventHeading>}
          {settings.subtitle && <EventText>{settings.subtitle}</EventText>}
          <div className={styles.buttons}>
            <EventButton variant="primary" tabIndex={-1}>
              {settings.start_button_text}
            </EventButton>
            <EventButton variant="secondary" tabIndex={-1}>
              Back
            </EventButton>
            <EventButton variant="primary" disabled>
              Print
            </EventButton>
          </div>
          <EventText muted>Choose a layout, then look at the camera.</EventText>
        </EventCard>

        <EventCard className={styles.details}>
          <EventText muted>
            {offered.length === 1
              ? '1 frame to choose from'
              : `${offered.length} frames to choose from`}
          </EventText>
          <EventInput
            id={`${prefix}-preview-email`}
            label="Email for your photos"
            placeholder="name@example.com"
            readOnly
            tabIndex={-1}
          />
          <EventMessage kind="success">Your photos are ready.</EventMessage>
          <EventMessage kind="warning">Paper is running low.</EventMessage>
          <EventMessage kind="error">The printer is not responding.</EventMessage>
        </EventCard>
      </div>
    </EventScreen>
  )
}

export function EventPreview({ settings, templates, frames }: EventPreviewProps) {
  const [mode, setMode] = useState<Mode>('preparation')
  const retakeText = RETAKE_LABELS[settings.retake_mode]
  const mirrorText = settings.mirror ? 'Mirror: on' : 'Mirror: off'
  const timeoutText = `Timeout: ${settings.inactivity_timeout_s} s`
  const layoutNames = offeredLayouts(settings.available_frames, frames ?? []).map(
    (key) => templates.find((t) => t.key === key)?.name ?? key,
  )

  return (
    <section
      aria-label="Event preview"
      data-testid="preparation-preview"
      className={styles.previewSection}
    >
      <div className={styles.previewTop}>
        <h2 className={styles.previewHeading}>Preview</h2>
        <div className={styles.modes} role="group" aria-label="Preview screen">
          {(
            [
              ['preparation', 'Preparation screen'],
              ['frames', 'Frame selection'],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={mode === value}
              className={styles.modeButton}
              onClick={() => setMode(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div data-testid="event-preview" className={styles.screenBox}>
        <PreviewScreen settings={settings} templates={templates} frames={frames} phone={false} mode={mode} />
      </div>
      <p className={styles.caption}>
        <span>{mirrorText}</span>, <span>{timeoutText}</span>, <span>{retakeText}</span>
        {layoutNames.length > 0 && <span>. Layouts offered: {layoutNames.join(', ')}</span>}
      </p>
      <h3 className={styles.phoneHeading}>Phone width</h3>
      <div className={`${styles.phoneFrame} ${styles.screenBox}`} data-testid="event-preview-phone">
        <PreviewScreen settings={settings} templates={templates} frames={frames} phone mode={mode} />
      </div>
    </section>
  )
}