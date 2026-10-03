import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'

import {
  ApiError,
  type BoothSessionState,
  type DecorateLayout,
  type DecorationCatalog,
} from '../../shared/api/client'
import { useApiClient } from '../../shared/api/ApiClientContext'
import {
  EventButton,
  EventHeading,
  EventMessage,
  EventScreen,
  EventText,
} from '../../shared/eventUi/EventUi'
import { BoothShell } from './BoothShell'
import { useBoothMenu } from './boothMenu'
import { useBoothServices } from './boothServices'
import { LEAVE_DEADLINE_MS, settleWithin } from './kiosk'
import { DecoratedPhoto } from './DecoratedPhoto'
import { FilterSwatch } from './FilterSwatch'
import { FinishDialog } from './FinishDialog'
import {
  countOn,
  type Decoration,
  editorReducer,
  forServer,
  initialEditor,
  ROTATE_STEP,
  shown,
  SIZE_STEP,
} from './decorationEditor'
import { useIdleTimeout, useKeepAlive } from './useIdleTimeout'
import styles from './DecoratePage.module.css'

/**
 * Decorating the finished photos: a filter for the photos and stickers on top, then Finish.
 *
 * Nothing here changes a file. The guest's choices stay on this screen until they confirm; the
 * booth then asks the server to make the finished photos with that decoration (once, whatever
 * happens: the request carries one key that a retry reuses) and the take-home screen follows.
 * A guest who wants none simply finishes: the photos are made exactly as they were taken.
 */

const BUSY_RETRIES = 8
const BUSY_WAIT_MS = 1500

function newKey(): string {
  return crypto.randomUUID().replaceAll('-', '')
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

type Stage = 'loading' | 'editing' | 'making' | 'failed'

/** States in which a visit is over. */
const ENDED = new Set(['completed', 'cancelled', 'abandoned', 'error'])
type Tab = 'stickers' | 'filters'

export function DecoratePage() {
  const api = useApiClient()
  const menu = useBoothMenu()
  const booth = useBoothServices()
  const [session, setSession] = useState<BoothSessionState | null>(null)
  const [layout, setLayout] = useState<DecorateLayout | null>(null)
  const [catalog, setCatalog] = useState<DecorationCatalog | null>(null)
  const [stage, setStage] = useState<Stage>('loading')
  const [problem, setProblem] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('stickers')
  const [active, setActive] = useState(1)
  // The decoration the guest is asked to confirm, frozen as it was on screen (P9-R1).
  const [confirming, setConfirming] = useState<Decoration | null>(null)
  const [leaving, setLeaving] = useState(false)
  const leavingNow = useRef(false)
  const making = useRef(false)
  const [editor, dispatch] = useReducer(editorReducer, undefined, initialEditor)
  // One key for this screen's request: a retry after a lost answer never makes a second set.
  const renderKey = useRef(newKey())

  // ---- the visit, its photos and what the booth offers ------------------------------------
  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const current = await api.currentSession()
        if (!alive) return
        if (!current) return booth.go('start', { replace: true })
        if (current.state === 'eligibility_ok') return booth.go('frames', { replace: true })
        if (current.state === 'capturing') return booth.go('capture', { replace: true })
        if (current.state === 'delivered') return booth.go('done', { replace: true })
        setSession(current)
        const [plan, offer] = await Promise.all([
          api.decorateLayout(current.id),
          api.decorations(),
        ])
        if (!alive) return
        setLayout(plan)
        setCatalog(offer)
        setStage('editing')
      } catch {
        if (!alive) return
        // The photos may have been made after all (a render settled on the server): go where
        // the visit really is rather than offering to decorate it again (P9-R2).
        const again = await api.currentSession().catch(() => undefined)
        if (!alive) return
        if (again === null) return booth.go('start', { replace: true })
        if (again?.state === 'delivered') return booth.go('done', { replace: true })
        setStage('failed')
        setProblem('Sorry, your photos could not be shown. Please start over.')
      }
    })()
    return () => {
      alive = false
    }
  }, [api, booth])

  // ---- leaving and finishing -------------------------------------------------------------
  const leave = useCallback(
    async (replace: boolean) => {
      if (leaving || leavingNow.current) return
      leavingNow.current = true // at once: a double tap on Done leaves once (Phase 12)
      setLeaving(true)
      // Leaving always works for the guest, even when the server does not answer in time: the
      // visit also ends by itself (P12-R1).
      if (session) await settleWithin(api.giveUpSession(session.id), LEAVE_DEADLINE_MS)
      booth.go('start', { replace })
    },
    [api, booth, leaving, session],
  )

  // Nobody there for the event's inactivity time: back to the start for the next guest. While
  // somebody is busy decorating, the server hears from the booth now and then, so it never ends
  // the visit as abandoned under them.
  useIdleTimeout(stage === 'making' ? undefined : session?.inactivity_timeout_s, () =>
    void leave(true),
  )
  // Only while decorating: once the photos are being made, the render itself keeps the visit
  // (and a read then would only wait for it) (P9-R3).
  const timeout = stage === 'editing' ? session?.inactivity_timeout_s : undefined
  useKeepAlive(timeout ? Math.max(5, Math.min(20, Math.floor(timeout / 3))) : undefined, () => {
    if (!session) return
    void api
      .readSession(session.id)
      .then((current) => {
        // The visit ended anyway (another screen, the organizer): say so instead of letting the
        // guest go on decorating something that can no longer be made (P9-R5).
        if (current.state === 'delivered') booth.go('done', { replace: true })
        else if (ENDED.has(current.state)) booth.go('start', { replace: true })
      })
      .catch(() => undefined)
  })

  /** Finish asks first, about exactly what is on screen: a finger still moving is let go. */
  const askToFinish = useCallback(() => {
    dispatch({ type: 'commit' })
    setConfirming(shown(editor))
  }, [editor])

  const finish = useCallback(async () => {
    if (!session || stage !== 'editing' || !confirming || making.current) return
    making.current = true // at once: a second press in the same frame makes nothing more (P12-R4)
    const decoration = forServer(confirming)
    setConfirming(null)
    setStage('making')
    try {
      for (let attempt = 0; ; attempt++) {
        try {
          await api.renderOutputs(session.id, renderKey.current, decoration)
          break
        } catch (error) {
          // The render worker is busy with somebody else's photos: nothing was recorded, so the
          // very same request is simply asked again a moment later.
          if (error instanceof ApiError && error.status === 503 && attempt < BUSY_RETRIES) {
            await wait(BUSY_WAIT_MS)
            continue
          }
          throw error
        }
      }
      booth.go('done', { replace: true })
    } catch {
      setStage('failed')
      setProblem('Sorry, your photos could not be made. Please start over.')
    }
  }, [api, booth, confirming, session, stage])

  // ---- what is on screen -----------------------------------------------------------------
  const tokens = menu.isSuccess ? menu.data.theme : {}
  // While the guest is asked to confirm, the screen shows exactly what will be made.
  const decoration = confirming ?? shown(editor)
  const art = useMemo(
    () => new Map((catalog?.stickers ?? []).map((sticker) => [sticker.key, sticker])),
    [catalog],
  )
  const filter = catalog?.filters.find((preset) => preset.key === decoration.filter)
  const outputs = layout?.outputs ?? []
  const limit = catalog?.max_stickers_per_photo ?? 0
  const full = countOn(editor.decoration, active) >= limit
  const chosen = editor.selected !== null
  const photoUrl = useCallback(
    (captureId: string, version: string | null) =>
      session ? api.captureImageUrl(session.id, captureId, version ?? undefined) : '',
    [api, session],
  )
  const many = outputs.length > 1

  return (
    <BoothShell>
      <EventScreen tokens={tokens} className={styles.screen} label="Decorate your photos">
        {(stage === 'loading' || stage === 'making') && (
          <div className={styles.making} role="status" data-testid="making-photos">
            <span className={styles.spinner} aria-hidden="true" />
            <EventHeading level={1}>
              {stage === 'making' ? 'Making your photos…' : 'Getting your photos…'}
            </EventHeading>
          </div>
        )}

        {stage === 'failed' && (
          <div className={styles.making} role="alert">
            <EventMessage kind="error">{problem}</EventMessage>
            <EventButton variant="primary" onClick={() => void leave(false)}>
              Start over
            </EventButton>
          </div>
        )}

        {stage === 'editing' && layout && catalog && session && (
          <>
            <div className={styles.header}>
              <EventHeading level={1}>Decorate your photos</EventHeading>
              <EventText muted>
                Add stickers and a filter, or finish straight away. Drag a sticker to move it;
                pinch to resize and turn it.
              </EventText>
            </div>

            <div className={styles.body}>
              <ul className={styles.outputs} data-count={outputs.length} aria-label="Your photos">
                {outputs.map((output) => {
                  const index = output.output_index
                  return (
                    <li
                      key={index}
                      className={styles.output}
                      data-active={!many || index === active ? '' : undefined}
                    >
                      <DecoratedPhoto
                        output={output}
                        mirror={layout.mirror}
                        frameUrl={layout.frame_url}
                        photoUrl={photoUrl}
                        filter={filter}
                        stickers={decoration.stickers.filter((s) => s.output === index)}
                        art={art}
                        label={many ? `Photo ${index} of ${outputs.length}` : 'Your photo'}
                        selected={confirming ? null : editor.selected}
                        frozen={confirming !== null}
                        onSelect={(id) => {
                          setActive(index)
                          dispatch({ type: 'select', id })
                        }}
                        onMove={(sticker) => dispatch({ type: 'move', sticker })}
                        onMoveEnd={() => dispatch({ type: 'commit' })}
                      />
                    </li>
                  )
                })}
              </ul>

              <section className={styles.tools} aria-label="Decorations">
                <div className={styles.tabs} role="tablist" aria-label="Decorations">
                  {(['stickers', 'filters'] as const).map((name) => (
                    <button
                      key={name}
                      type="button"
                      role="tab"
                      aria-selected={tab === name}
                      className={styles.tab}
                      onClick={() => setTab(name)}
                    >
                      {name === 'stickers' ? 'Stickers' : 'Filters'}
                    </button>
                  ))}
                </div>

                {tab === 'stickers' && (
                  <div className={styles.panel} role="tabpanel" aria-label="Stickers">
                    {many && (
                      <EventText muted>
                        New stickers go on photo {active}. Tap a photo to choose it.
                      </EventText>
                    )}
                    <div className={styles.stickers}>
                      {catalog.stickers.map((sticker) => (
                        <button
                          key={sticker.key}
                          type="button"
                          className={styles.stickerButton}
                          disabled={full}
                          aria-label={`Add ${sticker.label}`}
                          onClick={() =>
                            dispatch({ type: 'add', sticker: sticker.key, output: active, limit })
                          }
                        >
                          <img src={sticker.url} alt="" draggable={false} />
                        </button>
                      ))}
                    </div>
                    {full && (
                      <EventText muted>That photo has all the stickers it can take.</EventText>
                    )}
                  </div>
                )}

                {tab === 'filters' && (
                  <div className={styles.panel} role="tabpanel" aria-label="Filters">
                    <div className={styles.filters} role="radiogroup" aria-label="Filter">
                      {catalog.filters.map((preset) => (
                        <button
                          key={preset.key}
                          type="button"
                          role="radio"
                          aria-checked={editor.decoration.filter === preset.key}
                          className={styles.filterButton}
                          onClick={() => dispatch({ type: 'filter', filter: preset.key })}
                        >
                          {outputs[0] && (
                            <FilterSwatch
                              output={outputs[0]}
                              mirror={layout.mirror}
                              photoUrl={photoUrl}
                              filter={preset}
                            />
                          )}
                          {preset.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <div className={styles.selection} aria-label="Chosen sticker" role="group">
                  <EventButton
                    variant="secondary"
                    disabled={!chosen}
                    onClick={() => dispatch({ type: 'resize', factor: 1 / SIZE_STEP })}
                  >
                    Smaller
                  </EventButton>
                  <EventButton
                    variant="secondary"
                    disabled={!chosen}
                    onClick={() => dispatch({ type: 'resize', factor: SIZE_STEP })}
                  >
                    Bigger
                  </EventButton>
                  <EventButton
                    variant="secondary"
                    disabled={!chosen}
                    aria-label="Turn left"
                    onClick={() => dispatch({ type: 'rotate', degrees: -ROTATE_STEP })}
                  >
                    ↺
                  </EventButton>
                  <EventButton
                    variant="secondary"
                    disabled={!chosen}
                    aria-label="Turn right"
                    onClick={() => dispatch({ type: 'rotate', degrees: ROTATE_STEP })}
                  >
                    ↻
                  </EventButton>
                  <EventButton
                    variant="secondary"
                    disabled={!chosen}
                    onClick={() => dispatch({ type: 'remove' })}
                  >
                    Remove
                  </EventButton>
                </div>
              </section>
            </div>

            <div className={styles.actions}>
              <EventButton
                variant="secondary"
                disabled={editor.past.length === 0}
                onClick={() => dispatch({ type: 'undo' })}
              >
                Undo
              </EventButton>
              <EventButton
                variant="secondary"
                disabled={
                  editor.decoration.filter === 'none' && editor.decoration.stickers.length === 0
                }
                onClick={() => dispatch({ type: 'reset' })}
              >
                Start again
              </EventButton>
              <EventButton variant="primary" onClick={askToFinish}>
                Finish
              </EventButton>
            </div>

            {confirming && (
              <FinishDialog onKeep={() => setConfirming(null)} onFinish={() => void finish()} />
            )}
          </>
        )}
      </EventScreen>
    </BoothShell>
  )
}
