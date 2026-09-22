import type { Frame, TemplateSummary } from '../../shared/api/adminClient'
import type { GalleryFrame, GalleryPlan } from '../../shared/eventUi/framePlan'

/** "2×6" style label from the template's size in inches. */
export function layoutLabel(template: Pick<TemplateSummary, 'width_in' | 'height_in'>): string {
  return `${template.width_in}×${template.height_in}` // numbers print as 2, 3.5, ...
}

/** What choosing a frame of this layout means, as the participant screen shows it. */
export function planFromTemplate(template: TemplateSummary): GalleryPlan {
  const outputs = template.outputs_per_session
  const noun = template.key.startsWith('strip') ? 'strips' : 'prints'
  return {
    template_key: template.key,
    layout_label: layoutLabel(template),
    captures: template.captures_per_session,
    output_label: outputs > 1 ? `${outputs} ${noun}` : null,
  }
}

/**
 * The frames a profile offers, in its order, as the participant gallery shows them. Frames that
 * no longer exist or whose layout is unknown are left out (the booth does the same).
 */
export function galleryFrames(
  availableIds: string[],
  frames: Frame[],
  templates: TemplateSummary[],
  previewUrl: (frame: Frame) => string,
): GalleryFrame[] {
  const result: GalleryFrame[] = []
  for (const id of availableIds) {
    const frame = frames.find((f) => f.id === id)
    const template = frame && templates.find((t) => t.key === frame.template_key)
    if (!frame || !template) continue
    result.push({ id, name: frame.name, previewUrl: previewUrl(frame), plan: planFromTemplate(template) })
  }
  return result
}

/** Layout keys offered by these frames, in first-use order (the server's rule). */
export function offeredLayouts(availableIds: string[], frames: Frame[]): string[] {
  const layouts: string[] = []
  for (const id of availableIds) {
    const key = frames.find((f) => f.id === id)?.template_key
    if (key && !layouts.includes(key)) layouts.push(key)
  }
  return layouts
}
