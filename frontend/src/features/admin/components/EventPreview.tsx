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
import { RetryingImage } from './RetryingImage'
import styles from './EventPreview.module.css'

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
}

/**
 * One event screen drawn only from the draft settings. Button labels such as "Back" and the
 * example messages are fixed booth wording, never profile content; admin hints stay outside.
 */
function PreviewScreen({ settings, templates, frames, phone }: ScreenProps) {
  const api = useAdminApi()
  const backgroundUrl = settings.background_asset_id
    ? api.assetContentUrl(settings.background_asset_id)
    : null
  const logoUrl = settings.logo_asset_id ? api.assetContentUrl(settings.logo_asset_id) : null
  const firstLayout = settings.enabled_layouts[0]
  const template = templates.find((t) => t.key === firstLayout)
  const frameId = firstLayout ? settings.frame_selections?.[firstLayout] : undefined
  const frame = frameId ? frames?.find((f) => f.id === frameId) : undefined
  const prefix = phone ? 'phone' : 'wide'

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
          {frame ? (
            <figure className={styles.frameFigure}>
              <RetryingImage
                src={api.framePreviewUrl(frame.id, 1, frame.sha256)}
                alt={`${template?.name ?? 'Layout'} with ${frame.name}`}
                className={styles.frameImage}
              />
              <figcaption className={styles.frameCaption}>
                <EventText muted>
                  {frame.name}
                  {frame.builtin ? ' · Built-in' : ''}
                </EventText>
              </figcaption>
            </figure>
          ) : (
            firstLayout && <EventText muted>No frame for {template?.name ?? firstLayout}</EventText>
          )}
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
  const retakeText = RETAKE_LABELS[settings.retake_mode]
  const mirrorText = settings.mirror ? 'Mirror: on' : 'Mirror: off'
  const timeoutText = `Timeout: ${settings.inactivity_timeout_s} s`
  const layoutNames = settings.enabled_layouts.map(
    (key) => templates.find((t) => t.key === key)?.name ?? key,
  )

  return (
    <section
      aria-label="Preparation screen preview"
      data-testid="preparation-preview"
      className={styles.previewSection}
    >
      <h2 className={styles.previewHeading}>Preview</h2>
      <div data-testid="event-preview">
        <PreviewScreen settings={settings} templates={templates} frames={frames} phone={false} />
      </div>
      <p className={styles.caption}>
        <span>{mirrorText}</span>, <span>{timeoutText}</span>, <span>{retakeText}</span>
        {layoutNames.length > 0 && <span>. Layouts: {layoutNames.join(', ')}</span>}
      </p>
      <h3 className={styles.phoneHeading}>Phone width</h3>
      <div className={styles.phoneFrame} data-testid="event-preview-phone">
        <PreviewScreen settings={settings} templates={templates} frames={frames} phone />
      </div>
    </section>
  )
}
