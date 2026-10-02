/**
 * The guest's decoration while they make it: a filter and stickers, with undo and start-again.
 *
 * Pure state (no React, no DOM), so every rule is tested on its own. The numbers follow the
 * server's decoration: a sticker's centre `x`, `y` and its `size` (width) are fractions of the
 * finished photo, `rotation` is degrees clockwise in (-180, 180]. A move in progress (a finger
 * still on the sticker) is shown live but becomes one undo step only when the finger lifts.
 */

export const MIN_SIZE = 0.05
export const MAX_SIZE = 1
export const NEW_STICKER_SIZE = 0.32
export const SIZE_STEP = 1.2
export const ROTATE_STEP = 15

export interface PlacedSticker {
  /** Only for the screen (React keys, the chosen sticker); never sent to the server. */
  readonly id: number
  readonly sticker: string
  readonly output: number
  readonly x: number
  readonly y: number
  readonly size: number
  readonly rotation: number
}

export interface Decoration {
  readonly filter: string
  readonly stickers: readonly PlacedSticker[]
}

export interface EditorState {
  readonly decoration: Decoration
  /** Earlier decorations, newest last: what Undo goes back to. */
  readonly past: readonly Decoration[]
  /** The sticker the guest is working on, or null. */
  readonly selected: number | null
  /** A move in progress: shown, not yet an undo step. */
  readonly live: PlacedSticker | null
  readonly nextId: number
}

export type EditorAction =
  | { type: 'filter'; filter: string }
  | { type: 'add'; sticker: string; output: number; limit: number }
  | { type: 'select'; id: number | null }
  | { type: 'move'; sticker: PlacedSticker }
  | { type: 'commit' }
  | { type: 'resize'; factor: number }
  | { type: 'rotate'; degrees: number }
  | { type: 'remove' }
  | { type: 'undo' }
  | { type: 'reset' }

export const EMPTY: Decoration = { filter: 'none', stickers: [] }

export function initialEditor(): EditorState {
  return { decoration: EMPTY, past: [], selected: null, live: null, nextId: 1 }
}

export function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value))
}

/** Degrees folded into (-180, 180]. */
export function normalizeRotation(degrees: number): number {
  let turned = degrees % 360
  if (turned <= -180) turned += 360
  if (turned > 180) turned -= 360
  return turned === 0 ? 0 : turned // never -0
}

/** A sticker kept inside the rules the server checks (its centre on the photo, a sane size). */
export function settle(sticker: PlacedSticker): PlacedSticker {
  return {
    ...sticker,
    x: clamp(sticker.x, 0, 1),
    y: clamp(sticker.y, 0, 1),
    size: clamp(sticker.size, MIN_SIZE, MAX_SIZE),
    rotation: normalizeRotation(sticker.rotation),
  }
}

function changed(state: EditorState, decoration: Decoration, selected = state.selected): EditorState {
  return { ...state, decoration, past: [...state.past, state.decoration], selected, live: null }
}

function replaceSticker(stickers: readonly PlacedSticker[], next: PlacedSticker): PlacedSticker[] {
  return stickers.map((sticker) => (sticker.id === next.id ? next : sticker))
}

export function countOn(decoration: Decoration, output: number): number {
  return decoration.stickers.filter((sticker) => sticker.output === output).length
}

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  const chosen = state.decoration.stickers.find((sticker) => sticker.id === state.selected) ?? null
  switch (action.type) {
    case 'filter':
      if (action.filter === state.decoration.filter) return state
      return changed(state, { ...state.decoration, filter: action.filter })
    case 'add': {
      if (countOn(state.decoration, action.output) >= action.limit) return state
      const sticker: PlacedSticker = {
        id: state.nextId,
        sticker: action.sticker,
        output: action.output,
        x: 0.5,
        y: 0.5,
        size: NEW_STICKER_SIZE,
        rotation: 0,
      }
      return {
        ...changed(
          state,
          { ...state.decoration, stickers: [...state.decoration.stickers, sticker] },
          sticker.id,
        ),
        nextId: state.nextId + 1,
      }
    }
    case 'select':
      return { ...state, selected: action.id, live: null }
    case 'move':
      // Live while the finger moves; a sticker that is gone (undone meanwhile) is ignored.
      if (!state.decoration.stickers.some((sticker) => sticker.id === action.sticker.id)) {
        return state
      }
      return { ...state, live: settle(action.sticker), selected: action.sticker.id }
    case 'commit': {
      const live = state.live
      if (!live) return state
      const before = state.decoration.stickers.find((sticker) => sticker.id === live.id)
      if (!before || sameSpot(before, live)) return { ...state, live: null }
      return changed(state, {
        ...state.decoration,
        stickers: replaceSticker(state.decoration.stickers, live),
      })
    }
    case 'resize': {
      if (!chosen) return state
      const next = settle({ ...chosen, size: chosen.size * action.factor })
      if (sameSpot(chosen, next)) return state
      return changed(state, {
        ...state.decoration,
        stickers: replaceSticker(state.decoration.stickers, next),
      })
    }
    case 'rotate': {
      if (!chosen) return state
      const next = settle({ ...chosen, rotation: chosen.rotation + action.degrees })
      return changed(state, {
        ...state.decoration,
        stickers: replaceSticker(state.decoration.stickers, next),
      })
    }
    case 'remove':
      if (!chosen) return state
      return changed(
        state,
        {
          ...state.decoration,
          stickers: state.decoration.stickers.filter((sticker) => sticker.id !== chosen.id),
        },
        null,
      )
    case 'undo': {
      const previous = state.past.at(-1)
      if (!previous) return state
      const stillThere = previous.stickers.some((sticker) => sticker.id === state.selected)
      return {
        ...state,
        decoration: previous,
        past: state.past.slice(0, -1),
        selected: stillThere ? state.selected : null,
        live: null,
      }
    }
    case 'reset':
      if (state.decoration.filter === EMPTY.filter && state.decoration.stickers.length === 0) {
        return state
      }
      // Starting again is itself one step, so Undo brings the decoration back.
      return changed(state, EMPTY, null)
  }
}

function sameSpot(a: PlacedSticker, b: PlacedSticker): boolean {
  return a.x === b.x && a.y === b.y && a.size === b.size && a.rotation === b.rotation
}

/** What is on screen: the decoration with a move in progress applied. */
export function shown(state: EditorState): Decoration {
  const live = state.live
  if (!live) return state.decoration
  return { ...state.decoration, stickers: replaceSticker(state.decoration.stickers, live) }
}

/** The decoration as the server takes it (no screen ids; numbers rounded as the server keeps). */
export function forServer(decoration: Decoration) {
  const round = (value: number) => Math.round(value * 10_000) / 10_000
  return {
    filter: decoration.filter,
    stickers: decoration.stickers.map((sticker) => ({
      sticker: sticker.sticker,
      output: sticker.output,
      x: round(sticker.x),
      y: round(sticker.y),
      size: round(sticker.size),
      rotation: round(sticker.rotation),
    })),
  }
}
