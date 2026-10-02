import { boothHeaders, DEVICE_KEY_HEADER, type DeviceKeyStore } from './deviceKey'
import type { components } from './schema'

export type HealthResponse = components['schemas']['HealthResponse']
export type VersionResponse = components['schemas']['VersionResponse']
export type KioskStatusResponse = components['schemas']['KioskStatusResponse']
export type PingResponse = components['schemas']['PingResponse']
export type FrameMenu = components['schemas']['FrameMenuResponse']
export type BoothFrame = components['schemas']['BoothFrameResponse']
export type FramePlan = components['schemas']['FramePlanResponse']
export type BoothSessionState = components['schemas']['BoothSessionResponse']
export type CaptureResult = components['schemas']['CaptureResponse']
export type ShotState = components['schemas']['ShotResponse']
export type OutputState = components['schemas']['OutputResponse']
export type DeliveryLink = components['schemas']['DeliveryLinkResponse']
export type DecorationCatalog = components['schemas']['DecorationCatalogResponse']
export type DecorationFilter = components['schemas']['FilterResponse']
export type StickerOffer = components['schemas']['StickerResponse']
export type DecorateLayout = components['schemas']['DecorateLayoutResponse']
export type DecorateOutput = components['schemas']['DecorateOutputResponse']
export type DecorationRequest = components['schemas']['DecorationBody']

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export type Fetcher = (input: string, init?: RequestInit) => Promise<Response>

const noDeviceKey: DeviceKeyStore = { get: () => null, set: () => undefined, clear: () => undefined }

/** Typed client for the kiosk API. Same-origin only; the device cookie travels automatically. */
export function createApiClient(
  fetcher: Fetcher = (input, init) => fetch(input, init),
  deviceKeys: DeviceKeyStore = noDeviceKey,
) {
  async function getJson<T>(path: string): Promise<T> {
    const response = await fetcher(path, {
      headers: { Accept: 'application/json', ...boothHeaders(deviceKeys) },
      credentials: 'same-origin',
    })
    if (!response.ok) {
      throw new ApiError(response.status, `GET ${path} failed with ${response.status}`)
    }
    return (await response.json()) as T
  }

  /**
   * Device-authenticated mutation: the browser adds Origin; the device key comes from this
   * origin's storage (captured at pairing), never from a server response.
   */
  async function postJson<T>(path: string, body?: unknown): Promise<T> {
    const key = deviceKeys.get()
    if (!key) {
      throw new ApiError(401, 'kiosk is not paired in this browser')
    }
    const response = await fetcher(path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        [DEVICE_KEY_HEADER]: key,
        ...boothHeaders(deviceKeys),
      },
      body: body === undefined ? null : JSON.stringify(body),
    })
    if (response.status === 401 || response.status === 403) {
      deviceKeys.clear() // stale pairing (e.g. backend restarted): require re-pairing
    }
    if (!response.ok) {
      throw new ApiError(response.status, `POST ${path} failed with ${response.status}`)
    }
    return (await response.json()) as T
  }

  /** A photo of the session: multipart, device-authenticated, never retried under the same key. */
  async function postCapture(
    path: string,
    fields: Record<string, string>,
    photo: Blob,
  ): Promise<CaptureResult> {
    const key = deviceKeys.get()
    if (!key) {
      throw new ApiError(401, 'kiosk is not paired in this browser')
    }
    const form = new FormData()
    for (const [name, value] of Object.entries(fields)) form.append(name, value)
    form.append('file', photo, 'photo.jpg')
    const response = await fetcher(path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json', [DEVICE_KEY_HEADER]: key, ...boothHeaders(deviceKeys) },
      body: form,
    })
    if (response.status === 401 || response.status === 403) {
      deviceKeys.clear()
    }
    if (!response.ok) {
      throw new ApiError(response.status, `POST ${path} failed with ${response.status}`)
    }
    return (await response.json()) as CaptureResult
  }

  return {
    health: () => getJson<HealthResponse>('/api/health'),
    version: () => getJson<VersionResponse>('/api/version'),
    kioskStatus: () => getJson<KioskStatusResponse>('/api/kiosk/status'),
    hasDeviceKey: () => deviceKeys.get() !== null,
    boothPing: () => postJson<PingResponse>('/api/booth/ping'),
    /** Frames the active event offers to participants, in display order (404: no active event). */
    frameMenu: () => getJson<FrameMenu>('/api/booth/frames'),

    // ---- the visit itself (Phase 6) and its photos (Phase 7) ----------------------------
    /** Begin a visit. The same key never starts a second one (safe to retry). */
    startSession: (idempotencyKey: string) =>
      postJson<BoothSessionState>('/api/booth/sessions', { idempotency_key: idempotencyKey }),
    /** The visit this browser is in the middle of, or null (used after a reload). */
    currentSession: () => getJson<BoothSessionState | null>('/api/booth/sessions/current'),
    readSession: (sessionId: string) =>
      getJson<BoothSessionState>(`/api/booth/sessions/${sessionId}`),
    /** Confirm the frame: it fixes how many photos this visit takes. */
    chooseSessionFrame: (sessionId: string, frameId: string) =>
      postJson<BoothSessionState>(`/api/booth/sessions/${sessionId}/frame`, { frame_id: frameId }),
    /** Send one photo. The same key returns the first answer and stores nothing new. */
    sendCapture: (
      sessionId: string,
      photo: Blob,
      shot: { index: number; attempt: number; idempotencyKey: string },
    ) =>
      postCapture(
        `/api/booth/sessions/${sessionId}/captures`,
        {
          idempotency_key: shot.idempotencyKey,
          shot_index: String(shot.index),
          attempt_no: String(shot.attempt),
        },
        photo,
      ),
    /** One photo of this visit, for the screen that took it (a same-origin <img> source). */
    captureImageUrl: (sessionId: string, captureId: string, version?: string) =>
      `/api/booth/sessions/${sessionId}/captures/${captureId}.jpg${version ? `?v=${version}` : ''}`,
    /**
     * Take one photo again, or the whole set when no photo is named. `stateVersion` says which
     * state of the visit this answers, so a late second tap is refused rather than obeyed.
     */
    retakeCapture: (sessionId: string, shotIndex?: number, stateVersion?: number) =>
      postJson<BoothSessionState>(`/api/booth/sessions/${sessionId}/retake`, {
        ...(shotIndex === undefined ? {} : { shot_index: shotIndex }),
        ...(stateVersion === undefined ? {} : { state_version: stateVersion }),
      }),
    finishCaptures: (sessionId: string) =>
      postJson<BoothSessionState>(`/api/booth/sessions/${sessionId}/finish`),
    /** Make the finished photos. The same key never makes them twice (safe to retry). */
    /** The filters and stickers the booth offers, with the numbers the server applies. */
    decorations: () => getJson<DecorationCatalog>('/api/booth/decorations'),
    /** The finished photos as the server will compose them, for the decorating preview. */
    decorateLayout: (sessionId: string) =>
      getJson<DecorateLayout>(`/api/booth/sessions/${sessionId}/decorate`),
    /**
     * Make the finished photos, decorated as the guest chose (once: a retry reuses the key).
     */
    renderOutputs: (sessionId: string, idempotencyKey: string, decoration?: DecorationRequest) =>
      postJson<BoothSessionState>(`/api/booth/sessions/${sessionId}/render`, {
        idempotency_key: idempotencyKey,
        ...(decoration ? { decoration } : {}),
      }),
    /** One finished photo of this visit, for the booth screen (a same-origin <img> source). */
    outputImageUrl: (sessionId: string, outputId: string, version?: string) =>
      `/api/booth/sessions/${sessionId}/outputs/${outputId}.jpg${version ? `?v=${version}` : ''}`,
    /** The guest's take-home link and QR code (the same while the booth remembers it). */
    deliveryLink: (sessionId: string) =>
      postJson<DeliveryLink>(`/api/booth/sessions/${sessionId}/delivery`),
    /** The participant leaves: the visit ends and takes no more photos. */
    giveUpSession: (sessionId: string) =>
      postJson<BoothSessionState>(`/api/booth/sessions/${sessionId}/give-up`),
  }
}

export type ApiClient = ReturnType<typeof createApiClient>
