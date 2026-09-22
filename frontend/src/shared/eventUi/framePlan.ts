/** A frame as the participant gallery shows it, and what choosing it means for the session. */

export interface GalleryPlan {
  template_key: string
  layout_label: string
  captures: number
  output_label?: string | null | undefined
}

export interface GalleryFrame {
  id: string
  name: string
  previewUrl: string
  plan: GalleryPlan
}

export function planSummary(plan: GalleryPlan): string {
  const parts = [plan.layout_label, `${plan.captures} photos`]
  if (plan.output_label) parts.push(plan.output_label)
  return parts.join(' • ')
}

