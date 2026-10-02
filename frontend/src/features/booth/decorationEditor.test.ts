import { describe, expect, it } from 'vitest'

import {
  editorReducer,
  EMPTY,
  forServer,
  initialEditor,
  MAX_SIZE,
  MIN_SIZE,
  normalizeRotation,
  shown,
  type EditorAction,
  type EditorState,
  type PlacedSticker,
} from './decorationEditor'

function run(...actions: EditorAction[]): EditorState {
  return actions.reduce(editorReducer, initialEditor())
}

function firstSticker(state: EditorState): PlacedSticker {
  const sticker = state.decoration.stickers[0]
  if (!sticker) throw new Error('a sticker was added')
  return sticker
}

const add = (output = 1, sticker = 'heart', limit = 12): EditorAction => ({
  type: 'add',
  sticker,
  output,
  limit,
})

describe('the decoration editor', () => {
  it('adds a sticker in the middle of the chosen photo and chooses it', () => {
    const state = run(add(2))
    expect(state.decoration.stickers).toEqual([
      { id: 1, sticker: 'heart', output: 2, x: 0.5, y: 0.5, size: 0.32, rotation: 0 },
    ])
    expect(state.selected).toBe(1)
  })

  it('never puts more stickers on one photo than the server takes', () => {
    const state = run(add(1, 'heart', 2), add(1, 'star', 2), add(1, 'smiley', 2), add(2, 'star', 2))
    expect(state.decoration.stickers.map((s) => [s.output, s.sticker])).toEqual([
      [1, 'heart'],
      [1, 'star'],
      [2, 'star'],
    ])
  })

  it('shows a finger move live and makes the whole move one undo step', () => {
    let state = run(add())
    const sticker = firstSticker(state)
    state = editorReducer(state, { type: 'move', sticker: { ...sticker, x: 0.6 } })
    state = editorReducer(state, { type: 'move', sticker: { ...sticker, x: 0.7, y: 0.2 } })
    expect(shown(state).stickers[0]).toMatchObject({ x: 0.7, y: 0.2 })
    expect(state.decoration.stickers[0]).toMatchObject({ x: 0.5, y: 0.5 }) // not yet kept
    expect(state.past).toHaveLength(1)
    state = editorReducer(state, { type: 'commit' })
    expect(state.decoration.stickers[0]).toMatchObject({ x: 0.7, y: 0.2 })
    expect(state.past).toHaveLength(2)
    state = editorReducer(state, { type: 'undo' })
    expect(state.decoration.stickers[0]).toMatchObject({ x: 0.5, y: 0.5 })
  })

  it('a tap without a move is no undo step', () => {
    let state = run(add())
    const sticker = firstSticker(state)
    state = editorReducer(state, { type: 'move', sticker })
    state = editorReducer(state, { type: 'commit' })
    expect(state.past).toHaveLength(1)
  })

  it('keeps a sticker inside the rules the server checks', () => {
    let state = run(add())
    const sticker = firstSticker(state)
    state = editorReducer(state, {
      type: 'move',
      sticker: { ...sticker, x: -0.4, y: 1.7, size: 5, rotation: 350 },
    })
    state = editorReducer(state, { type: 'commit' })
    expect(state.decoration.stickers[0]).toMatchObject({ x: 0, y: 1, size: MAX_SIZE, rotation: -10 })
    for (let i = 0; i < 40; i++) state = editorReducer(state, { type: 'resize', factor: 0.5 })
    expect(state.decoration.stickers[0]?.size).toBe(MIN_SIZE)
  })

  it('turns, resizes and removes the chosen sticker only', () => {
    let state = run(add(1, 'heart'), add(1, 'star'))
    state = editorReducer(state, { type: 'rotate', degrees: 15 })
    state = editorReducer(state, { type: 'resize', factor: 1.2 })
    expect(state.decoration.stickers[1]).toMatchObject({ rotation: 15 })
    expect(state.decoration.stickers[1]?.size).toBeCloseTo(0.384)
    expect(state.decoration.stickers[0]).toMatchObject({ rotation: 0, size: 0.32 })
    state = editorReducer(state, { type: 'remove' })
    expect(state.decoration.stickers.map((s) => s.sticker)).toEqual(['heart'])
    expect(state.selected).toBeNull()
    expect(editorReducer(state, { type: 'remove' })).toBe(state) // nothing chosen: nothing gone
  })

  it('start again clears everything as one step that undo brings back', () => {
    let state = run({ type: 'filter', filter: 'sepia' }, add(), add(2))
    state = editorReducer(state, { type: 'reset' })
    expect(state.decoration).toEqual(EMPTY)
    expect(state.selected).toBeNull()
    state = editorReducer(state, { type: 'undo' })
    expect(state.decoration.filter).toBe('sepia')
    expect(state.decoration.stickers).toHaveLength(2)
    expect(editorReducer(run(), { type: 'reset' }).past).toHaveLength(0) // nothing to clear
  })

  it('undo walks back one step at a time and stops at the start', () => {
    let state = run({ type: 'filter', filter: 'mono' }, { type: 'filter', filter: 'warm' }, add())
    state = editorReducer(state, { type: 'undo' })
    expect(state.decoration.stickers).toHaveLength(0)
    expect(state.selected).toBeNull() // the undone sticker is no longer chosen
    state = editorReducer(state, { type: 'undo' })
    expect(state.decoration.filter).toBe('mono')
    state = editorReducer(editorReducer(state, { type: 'undo' }), { type: 'undo' })
    expect(state.decoration).toEqual(EMPTY)
    expect(state.past).toHaveLength(0)
  })

  it('choosing the filter already on is no step', () => {
    expect(run({ type: 'filter', filter: 'none' }).past).toHaveLength(0)
  })

  it('sends the server no screen ids, with numbers as the server keeps them', () => {
    let state = run({ type: 'filter', filter: 'cool' }, add(2))
    const sticker = firstSticker(state)
    state = editorReducer(state, {
      type: 'move',
      sticker: { ...sticker, x: 0.123456, rotation: -190 },
    })
    state = editorReducer(state, { type: 'commit' })
    expect(forServer(state.decoration)).toEqual({
      filter: 'cool',
      stickers: [{ sticker: 'heart', output: 2, x: 0.1235, y: 0.5, size: 0.32, rotation: 170 }],
    })
  })

  it('folds any angle into (-180, 180]', () => {
    expect([0, 180, -180, 190, -190, 360, 540, -0].map(normalizeRotation)).toEqual([
      0, 180, 180, -170, 170, 0, 180, 0,
    ])
    expect(Object.is(normalizeRotation(-360), -0)).toBe(false)
  })
})
