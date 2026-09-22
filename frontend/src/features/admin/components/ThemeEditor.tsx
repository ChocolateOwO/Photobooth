import { useId, useRef, useState } from 'react'

import {
  presetTheme,
  type EventTheme,
  type ThemeCatalog,
  type ThemePreset,
} from '../../../shared/api/adminClient'
import {
  contrastProblems,
  problemMessage,
  type ContrastProblem,
} from '../../../shared/eventTheme/theme'
import {
  EventButton,
  EventCard,
  EventDialog,
  EventHeading,
  EventInput,
  EventLink,
  EventMessage,
  EventScreen,
  EventText,
} from '../../../shared/eventUi/EventUi'
import { Icon } from './ui/Icon'
import { Modal } from './ui/Modal'
import styles from './ThemeEditor.module.css'

export interface ThemeExtraction {
  /** Re-run extraction on the current background. */
  reextract: () => void
  undo: () => void
  canUndo: boolean
  pending: boolean
  error: string | null
}

interface ThemeEditorProps {
  theme: EventTheme
  onChange: (theme: EventTheme) => void
  catalog: ThemeCatalog
  hasBackground: boolean
  extraction: ThemeExtraction
  /** The Button and Text colours as shown (the chosen ones while their shades are made). */
  mainColours: { button: string; text: string }
  /** Regenerate every related colour from new Button/Text colours. */
  onMainColours: (button: string, text: string) => void
  disabled: boolean
}


function Swatches({ colours, label }: { colours: string[]; label: string }) {
  return (
    <ul className={styles.swatches} aria-label={label}>
      {colours.map((colour, index) => (
        <li key={`${colour}-${index}`} className={styles.swatchItem}>
          <span className={styles.swatch} style={{ backgroundColor: colour }} aria-hidden="true" />
          <span className={styles.swatchHex}>{colour}</span>
        </li>
      ))}
    </ul>
  )
}

/** The three colours that tell presets apart at a glance. */
const TILE_TOKENS = ['background', 'primary_bg', 'secondary_bg'] as const

/** One compact option in the Quick theme strip: colour dots, name, selected mark, Details. */
function PresetOption({
  preset,
  checked,
  onSelect,
  onDetails,
  disabled,
  inputRef,
}: {
  preset: ThemePreset
  checked: boolean
  onSelect: () => void
  onDetails: (opener: HTMLButtonElement) => void
  disabled: boolean
  inputRef?: React.Ref<HTMLInputElement>
}) {
  return (
    <div className={styles.themeOption} data-selected={checked ? '' : undefined} data-testid="theme-option">
      <label className={styles.themeChoice}>
        <input
          ref={inputRef}
          type="radio"
          name="theme-preset"
          value={preset.id}
          checked={checked}
          onChange={onSelect}
          disabled={disabled}
          className={styles.themeRadio}
        />
        <span className={styles.dots} aria-hidden="true">
          {TILE_TOKENS.map((key) => (
            <span
              key={key}
              className={styles.dot}
              data-swatch=""
              style={{ backgroundColor: preset.tokens[key] ?? '#000000' }}
            />
          ))}
        </span>
        <span className={styles.themeName}>{preset.name}</span>
        {checked && (
          <span className={styles.check} aria-hidden="true">
            <Icon name="check" size={18} />
          </span>
        )}
      </label>
      <button
        type="button"
        className={styles.detailsIcon}
        onClick={(e) => onDetails(e.currentTarget)}
        aria-label={`View details of ${preset.name}`}
        title={`Details of ${preset.name}`}
      >
        <Icon name="details" size={18} />
      </button>
    </div>
  )
}

/** Everything about one preset; looking never selects it (only "Use ..." does). */
function PresetDetails({
  preset,
  catalog,
  checked,
  onApply,
  onClose,
}: {
  preset: ThemePreset
  catalog: ThemeCatalog
  checked: boolean
  onApply: () => void
  onClose: () => void
}) {
  return (
    <Modal
      title={preset.name}
      onClose={onClose}
      size="large"
      restoreFocus={false}
      footer={
        <div className={styles.dialogActions}>
          <button type="button" onClick={onApply} disabled={checked} className={styles.actionButton}>
            {checked ? 'This theme is selected' : `Use ${preset.name}`}
          </button>
        </div>
      }
    >
      <p className={styles.helper}>{preset.description}</p>
      <LiveExamples tokens={preset.tokens} />
      <table className={styles.tokenTable}>
        <caption className={styles.helper}>All {catalog.tokens.length} colours</caption>
        <tbody>
          {catalog.tokens.map((token) => (
            <tr key={token.key}>
              <th scope="row">{token.label}</th>
              <td>
                <span
                  className={styles.swatch}
                  style={{ backgroundColor: preset.tokens[token.key] ?? '#000000' }}
                  aria-hidden="true"
                />{' '}
                <span className={styles.swatchHex}>{preset.tokens[token.key]}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Modal>
  )
}
/** One main colour: a small round colour picker with its name and hex value. */
function MainColour({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  disabled: boolean
}) {
  return (
    <label className={styles.mainColour}>
      <input
        type="color"
        value={value.toLowerCase()}
        onChange={(e) => onChange(e.target.value.toUpperCase())}
        disabled={disabled}
        className={styles.roundPicker}
        aria-label={label}
      />
      <span className={styles.mainLabel}>
        <span>{label}</span>
        <span className={styles.swatchHex}>{value}</span>
      </span>
    </label>
  )
}

function LiveExamples({ tokens }: { tokens: Record<string, string> }) {
  return (
    <EventScreen tokens={tokens} className={styles.examples} label="Live theme examples">
      <div className={styles.examplesGrid}>
        <EventCard className={styles.exampleCard}>
          <EventHeading level={3}>Heading text</EventHeading>
          <EventText>Body text reads like this.</EventText>
          <EventText muted>Helper text is quieter.</EventText>
          <EventLink href="#theme-examples" onClick={(e) => e.preventDefault()}>
            A text link
          </EventLink>
        </EventCard>
        <div className={styles.exampleButtons}>
          <EventButton variant="primary" tabIndex={-1}>Main</EventButton>
          <EventButton variant="primary" demoState="hover" tabIndex={-1}>Hover</EventButton>
          <EventButton variant="primary" demoState="pressed" tabIndex={-1}>Pressed</EventButton>
          <EventButton variant="primary" disabled>Disabled</EventButton>
          <EventButton variant="secondary" tabIndex={-1}>Other</EventButton>
          <EventButton variant="secondary" demoState="hover" tabIndex={-1}>Hover</EventButton>
          <EventButton variant="secondary" demoState="pressed" tabIndex={-1}>Pressed</EventButton>
          <EventButton variant="secondary" disabled>Disabled</EventButton>
          <EventButton variant="danger" tabIndex={-1}>Delete</EventButton>
        </div>
        <div className={styles.exampleInputs}>
          <EventInput id="example-input-empty" label="Empty input" placeholder="Example text" readOnly tabIndex={-1} />
          <EventInput id="example-input-active" label="Active input" defaultValue="Typed text" demoFocus readOnly tabIndex={-1} />
        </div>
        <div className={styles.exampleMessages}>
          <EventMessage kind="success">Success message</EventMessage>
          <EventMessage kind="warning">Warning message</EventMessage>
          <EventMessage kind="error">Error message</EventMessage>
          <EventMessage kind="info">Information message</EventMessage>
        </div>
        <EventDialog title="Dialog on the backdrop">
          <EventText>Cards and dialogs use the surface colour.</EventText>
        </EventDialog>
      </div>
    </EventScreen>
  )
}

export function ThemeEditor({
  theme,
  onChange,
  catalog,
  hasBackground,
  extraction,
  mainColours,
  onMainColours,
  disabled,
}: ThemeEditorProps) {
  const firstPresetRef = useRef<HTMLInputElement>(null)
  const warningsId = useId()
  // One details view at a time; closing it returns focus and the page to where they were.
  const [detailsFor, setDetailsFor] = useState<string | null>(null)
  const openerRef = useRef<HTMLButtonElement | null>(null)
  const scrollRef = useRef(0)
  const openDetails = (presetId: string, opener: HTMLButtonElement) => {
    openerRef.current = opener
    scrollRef.current = window.scrollY
    setDetailsFor(presetId)
  }
  const closeDetails = () => {
    setDetailsFor(null)
    openerRef.current?.focus({ preventScroll: true })
    window.scrollTo({ top: scrollRef.current })
  }
  const detailsPreset = catalog.presets.find((p) => p.id === detailsFor)
  const labels = Object.fromEntries(catalog.tokens.map((t) => [t.key, t.label.toLowerCase()]))
  const problems: ContrastProblem[] = contrastProblems(theme.tokens, catalog.contrast_rules)
  const basePreset = catalog.presets.find((p) => p.id === theme.preset)
  const defaultPreset = catalog.presets.find((p) => p.id === catalog.default_preset)
  // The recommendation: the preset this theme started from, else the background's colours,
  // else the default preset.
  const resetToRecommended = () => {
    if (basePreset) onChange(presetTheme(basePreset))
    else if (hasBackground) extraction.reextract()
    else if (defaultPreset) onChange(presetTheme(defaultPreset))
  }

  return (
    <section className={styles.section} aria-labelledby="theme-heading">
      <h2 id="theme-heading" className={styles.sectionHeading}>
        Event theme
      </h2>
      <p className={styles.helper}>
        Colours for every screen guests see. These admin pages keep their own look.
      </p>

      <fieldset className={styles.fieldset} disabled={disabled}>
        <legend className={styles.legend}>Quick theme</legend>
        <div className={styles.themeStrip}>
          {catalog.presets.map((preset, index) => (
            <PresetOption
              key={preset.id}
              preset={preset}
              checked={theme.source === 'preset' && theme.preset === preset.id}
              onSelect={() => onChange(presetTheme(preset))}
              onDetails={(opener) => openDetails(preset.id, opener)}
              disabled={disabled}
              {...(index === 0 ? { inputRef: firstPresetRef } : {})}
            />
          ))}
        </div>
      </fieldset>
      {detailsPreset && (
        <PresetDetails
          preset={detailsPreset}
          catalog={catalog}
          checked={theme.source === 'preset' && theme.preset === detailsPreset.id}
          onApply={() => {
            onChange(presetTheme(detailsPreset))
            closeDetails()
          }}
          onClose={closeDetails}
        />
      )}

      <div className={styles.extractPanel}>
        <h3 className={styles.subHeading}>Colours from the background</h3>
        {!hasBackground ? (
          <p className={styles.helper}>
            Upload a background image under Images and its colours are used for the theme
            automatically.
          </p>
        ) : (
          <>
            {extraction.pending && (
              <p role="status" className={styles.helper}>
                Reading colours from the background…
              </p>
            )}
            {!extraction.pending && theme.source === 'extracted' && (
              <p role="status" className={styles.extracted}>
                Colors extracted from background
              </p>
            )}
            {(theme.palette ?? []).length > 0 && (
              <Swatches colours={theme.palette ?? []} label="Colours found in the background" />
            )}
            {extraction.error && (
              <div role="alert" className={styles.alert}>
                {extraction.error}
              </div>
            )}
            <div className={styles.actions}>
              <button
                type="button"
                onClick={extraction.reextract}
                disabled={disabled || extraction.pending}
                className={styles.actionButton}
              >
                Re-extract colors
              </button>
              <button
                type="button"
                onClick={extraction.undo}
                disabled={disabled || !extraction.canUndo || extraction.pending}
                className={styles.actionButton}
              >
                Undo extracted theme
              </button>
              <button
                type="button"
                onClick={() => firstPresetRef.current?.focus()}
                disabled={disabled}
                className={styles.actionButton}
              >
                Choose a preset instead
              </button>
            </div>
          </>
        )}
      </div>

      <div className={styles.mainColours} role="group" aria-labelledby="main-colours-heading">
        <h3 id="main-colours-heading" className={styles.subHeading}>
          Main colours
        </h3>
        <div className={styles.mainRow}>
          <MainColour
            label="Button colour"
            value={mainColours.button}
            onChange={(button) => onMainColours(button, mainColours.text)}
            disabled={disabled}
          />
          <MainColour
            label="Text colour"
            value={mainColours.text}
            onChange={(text) => onMainColours(mainColours.button, text)}
            disabled={disabled}
          />
          <button
            type="button"
            onClick={resetToRecommended}
            disabled={disabled || extraction.pending}
            className={styles.actionButton}
          >
            Reset to recommended colours
          </button>
        </div>
        <p className={styles.helper}>
          Hover, pressed and disabled shades, the other button, links, borders and helper text
          follow these two colours and stay readable.
        </p>
      </div>

      {problems.length > 0 ? (
        <div role="alert" className={styles.contrastWarning} id={warningsId} data-testid="contrast-warning">
          <p className={styles.contrastTitle}>
            Contrast warning: {problems.length} colour {problems.length === 1 ? 'pair is' : 'pairs are'}{' '}
            hard to read.
          </p>
          <ul>
            {problems.map((problem) => (
              <li key={`${problem.foreground}-${problem.background}`}>{problemMessage(problem, labels)}</li>
            ))}
          </ul>
          <p>You can still save, but guests may not be able to read these parts.</p>
        </div>
      ) : (
        <p className={styles.contrastOk} data-testid="contrast-ok">
          All text and buttons meet WCAG AA contrast.
        </p>
      )}
    </section>
  )
}
