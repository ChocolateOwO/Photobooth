import { useId, useRef, useState } from 'react'

import {
  presetTheme,
  type EventTheme,
  type ThemeCatalog,
  type ThemePreset,
} from '../../../shared/api/adminClient'
import {
  contrastProblems,
  isHexColor,
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
  disabled: boolean
}

const SWATCH_TOKENS = ['background', 'surface', 'heading', 'primary_bg', 'secondary_bg'] as const

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

function PresetCard({
  preset,
  checked,
  onSelect,
  disabled,
  inputRef,
}: {
  preset: ThemePreset
  checked: boolean
  onSelect: () => void
  disabled: boolean
  inputRef?: React.Ref<HTMLInputElement>
}) {
  return (
    <label className={styles.presetCard} data-selected={checked ? '' : undefined}>
      <input
        ref={inputRef}
        type="radio"
        name="theme-preset"
        value={preset.id}
        checked={checked}
        onChange={onSelect}
        disabled={disabled}
        className={styles.presetRadio}
        aria-describedby={`preset-desc-${preset.id}`}
      />
      <span className={styles.presetName}>{preset.name}</span>
      <span id={`preset-desc-${preset.id}`} className={styles.presetDescription}>
        {preset.description}
      </span>
      <Swatches
        colours={SWATCH_TOKENS.map((key) => preset.tokens[key] ?? '#000000')}
        label={`${preset.name} colours`}
      />
      <EventScreen tokens={preset.tokens} className={styles.presetSample}>
        <span className={styles.presetSampleHeading}>Aa</span>
        <span className={styles.presetSampleText}>Welcome</span>
        <span className={styles.presetSampleButtons} aria-hidden="true">
          <EventButton variant="primary" tabIndex={-1}>
            Start
          </EventButton>
          <EventButton variant="secondary" tabIndex={-1}>
            Back
          </EventButton>
        </span>
      </EventScreen>
    </label>
  )
}

function ColourField({
  tokenKey,
  label,
  description,
  value,
  problem,
  onChange,
  disabled,
}: {
  tokenKey: string
  label: string
  description: string
  value: string
  problem: boolean
  onChange: (value: string) => void
  disabled: boolean
}) {
  const [draft, setDraft] = useState(value)
  const [shown, setShown] = useState(value)
  if (shown !== value) {
    // The token changed elsewhere (preset, reset, extraction): show the new value.
    setShown(value)
    setDraft(value)
  }
  const descId = `token-desc-${tokenKey}`
  return (
    <div className={styles.colourRow} data-token={tokenKey}>
      <div className={styles.colourText}>
        <label htmlFor={`token-${tokenKey}`} className={styles.colourLabel}>
          {label}
        </label>
        <span id={descId} className={styles.colourDescription}>
          {description}
        </span>
        {problem && <span className={styles.colourWarning}>Low contrast</span>}
      </div>
      <div className={styles.colourInputs}>
        <input
          id={`token-${tokenKey}`}
          type="color"
          value={value.toLowerCase()}
          aria-describedby={descId}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          disabled={disabled}
          className={styles.colourPicker}
        />
        <input
          type="text"
          aria-label={`${label} hex value`}
          value={draft}
          maxLength={7}
          spellCheck={false}
          onChange={(e) => {
            const next = e.target.value.trim()
            setDraft(next)
            if (isHexColor(next)) onChange(next.toUpperCase())
          }}
          disabled={disabled}
          className={styles.hexInput}
        />
      </div>
    </div>
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
  disabled,
}: ThemeEditorProps) {
  const firstPresetRef = useRef<HTMLInputElement>(null)
  const warningsId = useId()
  const labels = Object.fromEntries(catalog.tokens.map((t) => [t.key, t.label.toLowerCase()]))
  const problems: ContrastProblem[] = contrastProblems(theme.tokens, catalog.contrast_rules)
  const troubled = new Set(problems.flatMap((p) => [p.foreground, p.background]))
  const basePreset = catalog.presets.find((p) => p.id === theme.preset)
  const groups = [...new Set(catalog.tokens.map((t) => t.group))]

  const setToken = (key: string, value: string) => {
    onChange({
      ...theme,
      tokens: { ...theme.tokens, [key]: value },
      source: 'custom',
    })
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
        <div className={styles.presetGrid}>
          {catalog.presets.map((preset, index) => (
            <PresetCard
              key={preset.id}
              preset={preset}
              checked={theme.source === 'preset' && theme.preset === preset.id}
              onSelect={() => onChange(presetTheme(preset))}
              disabled={disabled}
              {...(index === 0 ? { inputRef: firstPresetRef } : {})}
            />
          ))}
        </div>
      </fieldset>

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

      <details className={styles.advanced}>
        <summary className={styles.summary}>Advanced colors</summary>
        <p className={styles.helper}>
          Change any single colour. Each one says what it changes on the guest screens.
        </p>
        <button
          type="button"
          onClick={() => basePreset && onChange(presetTheme(basePreset))}
          disabled={disabled || !basePreset}
          className={styles.actionButton}
        >
          Reset to selected preset
        </button>
        {!basePreset && (
          <p className={styles.helper}>Choose a quick theme first to be able to reset to it.</p>
        )}
        <LiveExamples tokens={theme.tokens} />
        {groups.map((group) => (
          <fieldset key={group} className={styles.fieldset} disabled={disabled}>
            <legend className={styles.legend}>{group}</legend>
            {catalog.tokens
              .filter((t) => t.group === group)
              .map((t) => (
                <ColourField
                  key={t.key}
                  tokenKey={t.key}
                  label={t.label}
                  description={t.description}
                  value={theme.tokens[t.key] ?? '#000000'}
                  problem={troubled.has(t.key)}
                  onChange={(value) => setToken(t.key, value)}
                  disabled={disabled}
                />
              ))}
          </fieldset>
        ))}
      </details>

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
