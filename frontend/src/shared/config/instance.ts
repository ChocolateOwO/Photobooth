export type InstanceName = 'dummy' | 'main'

/** Instance baked in at build time. Anything not explicitly "main" is treated as Dummy. */
export const buildInstance: InstanceName = __PHOTOBOOTH_INSTANCE__ === 'main' ? 'main' : 'dummy'
