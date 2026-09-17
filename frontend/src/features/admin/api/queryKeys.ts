/** Every admin-only query lives under this root so a lost session can drop them all at once. */
export const ADMIN_QUERY_ROOT = ['admin'] as const
