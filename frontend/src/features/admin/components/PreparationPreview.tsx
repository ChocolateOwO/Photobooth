import type { CSSProperties } from 'react'

import type { ProfileSettings, RetakeMode, TemplateSummary } from '../../../shared/api/adminClient'
import { useAdminApi } from '../../../shared/api/AdminApiContext'
import styles from './PreparationPreview.module.css'

interface PreparationPreviewProps {
  settings: ProfileSettings
  templates: TemplateSummary[]
}

const RETAKE_LABELS: Record<RetakeMode, string> = {
  none: 'No retakes',
  per_photo: 'Retake any single photo',
  all: 'Retake all photos',
}

export function PreparationPreview({ settings, templates }: PreparationPreviewProps) {
  const api = useAdminApi()

  const bgUrl = settings.background_asset_id
    ? api.assetContentUrl(settings.background_asset_id)
    : null
  const logoUrl = settings.logo_asset_id ? api.assetContentUrl(settings.logo_asset_id) : null

  const mockStyle: CSSProperties = {
    backgroundColor: settings.background_color,
    ...(bgUrl
      ? {
          // Quoted; the URL is built by the admin client from an encoded asset id.
          backgroundImage: `url("${bgUrl}")`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          backgroundRepeat: 'no-repeat',
        }
      : {}),
    color: settings.text_color,
  }

  const enabledLayoutNames = settings.enabled_layouts.map((key) => {
    const found = templates.find((t) => t.key === key)
    return found ? found.name : key
  })

  const retakeText = RETAKE_LABELS[settings.retake_mode] ?? 'Retake any single photo'
  const mirrorText = settings.mirror ? 'Mirror: on' : 'Mirror: off'
  const timeoutText = `Timeout: ${settings.inactivity_timeout_s} s`

  return (
    <section
      aria-label="Preparation screen preview"
      data-testid="preparation-preview"
      className={styles.previewSection}
    >
      <figure className={styles.figure}>
        <div className={styles.screenMock} style={mockStyle}>
          <div className={styles.headerZone}>
            {logoUrl && <img src={logoUrl} alt="Preview logo" className={styles.logo} />}
            <h2 className={styles.title} style={{ color: settings.text_color }}>
              {settings.title}
            </h2>
            {settings.subtitle && (
              <p className={styles.subtitle} style={{ color: settings.text_color }}>
                {settings.subtitle}
              </p>
            )}
          </div>

          <div className={styles.centerZone}>
            <div
              className={styles.startButton}
              style={{
                backgroundColor: settings.button_color,
              }}
            >
              {settings.start_button_text || 'Start'}
            </div>
          </div>

          <div className={styles.footerZone}>
            {enabledLayoutNames.length > 0 && (
              <div className={styles.chips}>
                {enabledLayoutNames.map((name) => (
                  <span
                    key={name}
                    className={styles.layoutChip}
                    style={{
                      backgroundColor: settings.primary_color,
                      color: settings.secondary_color,
                      borderColor: settings.secondary_color,
                    }}
                  >
                    {name}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <figcaption className={styles.caption}>
          <span>{mirrorText}</span>, <span>{timeoutText}</span>, <span>{retakeText}</span>
        </figcaption>
      </figure>
    </section>
  )
}
