import type { Frame, ProfileSettings, ThemeCatalog } from '../../shared/api/adminClient'

/**
 * The built-in frame family a new selection should use: the family already chosen for another
 * layout of this profile, else the family that suits the theme's preset, else Midnight.
 */
export function preferredFamily(
  settings: ProfileSettings,
  frames: Frame[],
  catalog: ThemeCatalog,
): string {
  const chosen = Object.values(settings.frame_selections ?? {})
    .map((id) => frames.find((f) => f.id === id))
    .find((f) => f?.builtin && f.family)
  if (chosen?.family) return chosen.family
  const preset = catalog.presets.find((p) => p.id === settings.theme.preset)
  return preset?.frame_family ?? 'midnight'
}

/** The built-in frame of a family for a layout (any built-in one when that family is missing). */
export function builtinFrameFor(
  frames: Frame[],
  templateKey: string,
  family: string,
): Frame | undefined {
  return (
    frames.find((f) => f.builtin && f.template_key === templateKey && f.family === family) ??
    frames.find((f) => f.builtin && f.template_key === templateKey)
  )
}
