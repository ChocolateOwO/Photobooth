import { useState, type ChangeEvent } from 'react'

import {
  ACCEPTED_IMAGE_TYPES,
  AdminApiError,
  ASSET_LIMITS,
  type AssetKind,
} from '../../../shared/api/adminClient'
import { useAdminApi } from '../../../shared/api/AdminApiContext'
import { BigButton } from '../../../shared/ui/BigButton'
import { useAsset, useUploadAsset } from '../api/hooks'
import styles from './AssetPicker.module.css'

interface AssetPickerProps {
  kind: AssetKind
  assetId: string | null | undefined
  onChange: (assetId: string | null) => void
  /** Reports upload start/end so the form can block saving meanwhile. */
  onUploadingChange?: (active: boolean) => void
  disabled?: boolean
}

export function AssetPicker({
  kind,
  assetId,
  onChange,
  onUploadingChange,
  disabled = false,
}: AssetPickerProps) {
  const api = useAdminApi()
  const { data: asset } = useAsset(assetId)
  const uploadMutation = useUploadAsset()

  const [clientError, setClientError] = useState<string | null>(null)
  const [serverErrors, setServerErrors] = useState<string[] | null>(null)

  const isLogo = kind === 'logo'
  const labelText = isLogo ? 'Logo image' : 'Background image'
  const altText = isLogo ? 'Logo preview' : 'Background preview'
  const removeText = isLogo ? 'Remove logo' : 'Remove background'
  const inputId = `asset-input-${kind}`

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setClientError(null)
    setServerErrors(null)

    const isAcceptedType = (ACCEPTED_IMAGE_TYPES as readonly string[]).includes(file.type)
    if (!isAcceptedType) {
      setClientError(
        isLogo ? 'Logo must be a PNG or JPEG image.' : 'Background must be a PNG or JPEG image.',
      )
      e.target.value = ''
      return
    }

    const limits = ASSET_LIMITS[kind]
    if (file.size > limits.maxBytes) {
      setClientError(
        isLogo ? 'Logo must be 5 MB or smaller.' : 'Background must be 12 MB or smaller.',
      )
      e.target.value = ''
      return
    }

    onUploadingChange?.(true)
    try {
      const uploaded = await uploadMutation.mutateAsync({ kind, file })
      onChange(uploaded.id)
    } catch (err: unknown) {
      if (err instanceof AdminApiError) {
        setServerErrors(err.messages.length > 0 ? err.messages : [err.message])
      } else if (err instanceof Error) {
        setServerErrors([err.message])
      } else {
        setServerErrors(['Upload failed.'])
      }
    } finally {
      onUploadingChange?.(false)
      e.target.value = ''
    }
  }

  const handleRemove = () => {
    setClientError(null)
    setServerErrors(null)
    onChange(null)
  }

  return (
    <div className={styles.container}>
      <label htmlFor={inputId} className={styles.label}>
        {labelText}
      </label>

      <input
        id={inputId}
        type="file"
        accept="image/png,image/jpeg"
        aria-describedby={`help-asset-${kind}`}
        onChange={(e) => {
          void handleFileChange(e)
        }}
        disabled={disabled || uploadMutation.isPending}
        className={styles.fileInput}
      />

      <p id={`help-asset-${kind}`} className={styles.helperText}>
        {isLogo
          ? 'PNG or JPEG, up to 5 MB. A transparent PNG works best.'
          : 'PNG or JPEG, up to 12 MB. A 16:9 image fills the screen best.'}
      </p>

      {uploadMutation.isPending && <p className={styles.uploading}>Uploading…</p>}

      {(clientError !== null || (serverErrors !== null && serverErrors.length > 0)) && (
        <div role="alert" className={styles.alert}>
          {clientError !== null && <p>{clientError}</p>}
          {serverErrors?.map((msg, idx) => (
            <p key={idx}>{msg}</p>
          ))}
        </div>
      )}

      {assetId && (
        <div className={styles.previewCard}>
          <img src={api.assetContentUrl(assetId)} alt={altText} className={styles.previewImage} />
          <div className={styles.previewInfo}>
            {asset && (
              <span className={styles.dimensions}>
                {asset.width} × {asset.height} px
              </span>
            )}
            <BigButton
              type="button"
              onClick={handleRemove}
              disabled={disabled}
              className={styles.removeButton}
            >
              {removeText}
            </BigButton>
          </div>
        </div>
      )}
    </div>
  )
}
