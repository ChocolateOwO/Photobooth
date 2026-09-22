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

function byLibraryOrder(a: Frame, b: Frame): number {
  // The server's order: built-in frames first, then names (code-point order, like SQLite).
  if (a.builtin !== b.builtin) return a.builtin ? -1 : 1
  return a.name < b.name ? -1 : a.name > b.name ? 1 : 0
}

/**
 * The valid frames of these photo sizes, as the booth offers them: sizes in the given order,
 * then built-in frames first and names A-Z. Frames of unknown layouts are left out.
 */
export function framesForSizes(layouts: string[], frames: Frame[], templates: TemplateSummary[]): Frame[] {
  return layouts.flatMap((key) =>
    templates.some((t) => t.key === key)
      ? frames.filter((f) => f.template_key === key && f.status === 'valid').sort(byLibraryOrder)
      : [],
  )
}

/** What participants see for these sizes, in the participant gallery's shape. */
export function galleryFrames(
  layouts: string[],
  frames: Frame[],
  templates: TemplateSummary[],
  previewUrl: (frame: Frame) => string,
): GalleryFrame[] {
  return framesForSizes(layouts, frames, templates).map((frame) => {
    const template = templates.find((t) => t.key === frame.template_key) as TemplateSummary
    return { id: frame.id, name: frame.name, previewUrl: previewUrl(frame), plan: planFromTemplate(template) }
  })
}

/** Chosen sizes that actually have at least one valid frame (what the booth can offer). */
export function offeredLayouts(layouts: string[], frames: Frame[], templates: TemplateSummary[]): string[] {
  return layouts.filter((key) => framesForSizes([key], frames, templates).length > 0)
}
