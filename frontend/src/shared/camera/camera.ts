/**
 * The booth's camera, behind one small port.
 *
 * The booth screen never talks to `getUserMedia` itself: it asks a `CameraSource` for a live
 * picture and for single photos. Dummy can therefore run a drawn test camera that needs no
 * hardware and produces a different, predictable photo every time, while the real booth uses the
 * browser camera. Nothing above this file knows which one it got.
 */

export type CameraProblem =
  | 'denied' // the person (or policy) refused the camera
  | 'missing' // no camera on this machine
  | 'in-use' // another program holds the camera
  | 'lost' // the camera went away while the booth was using it
  | 'insecure' // browsers only give cameras to secure pages
  | 'failed' // anything else

export class CameraError extends Error {
  readonly problem: CameraProblem

  constructor(problem: CameraProblem, message: string) {
    super(message)
    this.name = 'CameraError'
    this.problem = problem
  }
}

export interface CameraDevice {
  id: string
  label: string
}

export interface CameraView {
  /** The live picture for the preview element. */
  readonly stream: MediaStream
  /** One photo, as the camera sees it (never mirrored: the mirror is a render setting). */
  photo(): Promise<Blob>
  /** True while the camera is still delivering pictures. */
  live(): boolean
  stop(): void
}

export interface CameraSource {
  readonly kind: 'browser' | 'test' | 'pc'
  /** Cameras to choose from; may be empty before permission is granted. */
  devices(): Promise<CameraDevice[]>
  open(deviceId?: string): Promise<CameraView>
}

export const CAPTURE_WIDTH = 1280
export const CAPTURE_HEIGHT = 960
const JPEG_QUALITY = 0.95

function problemOf(error: unknown): CameraProblem {
  const name = error instanceof Error ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'denied'
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'missing'
  if (name === 'NotReadableError' || name === 'AbortError') return 'in-use'
  return 'failed'
}

export function cameraMessage(problem: CameraProblem): string {
  switch (problem) {
    case 'denied':
      return 'The camera is blocked for this booth. Allow it in the browser, then try again.'
    case 'missing':
      return 'No camera is connected to this booth.'
    case 'in-use':
      return 'Another program is using the camera. Close it, then try again.'
    case 'lost':
      return 'The camera was disconnected.'
    case 'insecure':
      return 'The booth must be opened on this machine (127.0.0.1) for the camera to work.'
    default:
      return 'The camera could not be started.'
  }
}

async function toJpeg(canvas: HTMLCanvasElement): Promise<Blob> {
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY),
  )
  if (!blob) throw new CameraError('failed', 'the photo could not be made')
  return blob
}

/** Draws a picture at capture size, cropped to fill (never stretched). */
function drawCover(
  picture: CanvasImageSource,
  width: number,
  height: number,
  canvas: HTMLCanvasElement,
): void {
  const context = canvas.getContext('2d')
  if (!context) throw new CameraError('failed', 'this browser can not take photos')
  const scale = Math.max(canvas.width / width, canvas.height / height)
  const drawWidth = width * scale
  const drawHeight = height * scale
  context.drawImage(
    picture,
    (canvas.width - drawWidth) / 2,
    (canvas.height - drawHeight) / 2,
    drawWidth,
    drawHeight,
  )
}

/** The real camera of this machine, through the browser. */
export class BrowserCamera implements CameraSource {
  readonly kind = 'browser'

  async devices(): Promise<CameraDevice[]> {
    if (!navigator.mediaDevices?.enumerateDevices) return []
    const found = await navigator.mediaDevices.enumerateDevices()
    return found
      .filter((device) => device.kind === 'videoinput')
      .map((device, index) => ({
        id: device.deviceId,
        label: device.label || `Camera ${index + 1}`,
      }))
  }

  async open(deviceId?: string): Promise<CameraView> {
    if (!navigator.mediaDevices?.getUserMedia) {
      // Browsers hand out cameras only to secure pages (127.0.0.1 counts, a LAN address does not).
      throw new CameraError('insecure', cameraMessage('insecure'))
    }
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: CAPTURE_WIDTH },
          height: { ideal: CAPTURE_HEIGHT },
          ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
        },
        audio: false,
      })
    } catch (error) {
      const problem = problemOf(error)
      throw new CameraError(problem, cameraMessage(problem))
    }
    const video = document.createElement('video')
    video.srcObject = stream
    video.muted = true
    video.playsInline = true
    try {
      await video.play()
    } catch {
      // Autoplay refusals do not stop a muted stream from delivering pictures.
    }
    const canvas = document.createElement('canvas')
    canvas.width = CAPTURE_WIDTH
    canvas.height = CAPTURE_HEIGHT
    return {
      stream,
      live: () => stream.getVideoTracks().some((track) => track.readyState === 'live'),
      async photo() {
        if (!stream.getVideoTracks().some((track) => track.readyState === 'live')) {
          throw new CameraError('lost', cameraMessage('lost'))
        }
        drawCover(
          video,
          video.videoWidth || CAPTURE_WIDTH,
          video.videoHeight || CAPTURE_HEIGHT,
          canvas,
        )
        return toJpeg(canvas)
      },
      stop() {
        for (const track of stream.getTracks()) track.stop()
        video.srcObject = null
      },
    }
  }
}

/**
 * A drawn camera for Dummy: no hardware, and every photo differs from the last one, so tests can
 * prove that six photos of a strip are six different pictures.
 */
export class TestCamera implements CameraSource {
  readonly kind = 'test'
  private frame = 0

  async devices(): Promise<CameraDevice[]> {
    return [{ id: 'test-camera', label: 'Test camera (Dummy)' }]
  }

  async open(): Promise<CameraView> {
    const canvas = document.createElement('canvas')
    canvas.width = CAPTURE_WIDTH
    canvas.height = CAPTURE_HEIGHT
    const context = canvas.getContext('2d')
    if (!context) throw new CameraError('failed', 'this browser can not draw the test camera')
    let stopped = false
    const draw = (): void => {
      this.frame += 1
      const shade = (this.frame * 7) % 200
      context.fillStyle = `rgb(${30 + shade}, ${70 + (shade % 90)}, 150)`
      context.fillRect(0, 0, canvas.width, canvas.height)
      context.fillStyle = '#ffffff'
      context.font = 'bold 120px sans-serif'
      context.textAlign = 'center'
      context.fillText(String(this.frame), canvas.width / 2, canvas.height / 2)
      context.font = '40px sans-serif'
      context.fillText('Test camera', canvas.width / 2, canvas.height / 2 + 90)
      // A moving marker, so a still picture is never mistaken for a live one.
      context.fillRect((this.frame * 37) % canvas.width, canvas.height - 60, 60, 30)
    }
    draw()
    const timer = window.setInterval(() => {
      if (!stopped) draw()
    }, 100)
    const stream =
      typeof canvas.captureStream === 'function' ? canvas.captureStream(10) : new MediaStream()
    return {
      stream,
      live: () => !stopped,
      async photo() {
        if (stopped) throw new CameraError('lost', cameraMessage('lost'))
        draw()
        return toJpeg(canvas)
      },
      stop() {
        stopped = true
        window.clearInterval(timer)
        for (const track of stream.getTracks()) track.stop()
      },
    }
  }
}

const PC_FRAME_PATH = '/api/booth/camera/frame.jpg'
const PC_PREVIEW_PAUSE_MS = 60
const PC_RETRY_PAUSE_MS = 500
const PC_FAILURES_UNTIL_LOST = 3

const pause = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms))

type FrameFetcher = (path: string) => Promise<Response>

/**
 * The booth PC's own camera, for a booth screen on another device (a TV's browser on the LAN).
 *
 * The PC takes the pictures; this screen only shows them. The live picture is a quick run of
 * small stills, and each photo is one full-size still, cropped exactly like the browser camera's.
 * Which PC camera is used is chosen in Admin on the PC.
 */
export class PcCamera implements CameraSource {
  readonly kind = 'pc'
  private readonly fetchFrame: FrameFetcher

  constructor(
    fetcher: FrameFetcher = (path) => fetch(path, { credentials: 'same-origin', cache: 'no-store' }),
  ) {
    this.fetchFrame = fetcher
  }

  async devices(): Promise<CameraDevice[]> {
    return [{ id: 'pc-camera', label: 'Booth PC camera' }]
  }

  private async still(preview: boolean): Promise<ImageBitmap> {
    let response: Response
    try {
      response = await this.fetchFrame(preview ? `${PC_FRAME_PATH}?preview=true` : PC_FRAME_PATH)
    } catch {
      throw new CameraError('lost', cameraMessage('lost'))
    }
    if (response.status === 503) throw new CameraError('missing', cameraMessage('missing'))
    if (!response.ok) throw new CameraError('failed', cameraMessage('failed'))
    try {
      return await createImageBitmap(await response.blob())
    } catch {
      throw new CameraError('failed', cameraMessage('failed'))
    }
  }

  async open(): Promise<CameraView> {
    const first = await this.still(true) // no picture: the booth says so before any countdown
    const canvas = document.createElement('canvas')
    canvas.width = CAPTURE_WIDTH
    canvas.height = CAPTURE_HEIGHT
    const photoCanvas = document.createElement('canvas')
    photoCanvas.width = CAPTURE_WIDTH
    photoCanvas.height = CAPTURE_HEIGHT
    const show = (picture: ImageBitmap) => {
      drawCover(picture, picture.width, picture.height, canvas)
      picture.close()
    }
    show(first)
    let stopped = false
    let failures = 0
    void (async () => {
      while (!stopped) {
        try {
          const picture = await this.still(true)
          if (stopped) {
            picture.close()
            break
          }
          show(picture)
          failures = 0
          await pause(PC_PREVIEW_PAUSE_MS)
        } catch {
          failures += 1
          await pause(PC_RETRY_PAUSE_MS)
        }
      }
    })()
    const stream =
      typeof canvas.captureStream === 'function' ? canvas.captureStream(15) : new MediaStream()
    const live = () => !stopped && failures < PC_FAILURES_UNTIL_LOST
    return {
      stream,
      live,
      photo: async () => {
        if (!live()) throw new CameraError('lost', cameraMessage('lost'))
        const picture = await this.still(false)
        drawCover(picture, picture.width, picture.height, photoCanvas)
        picture.close()
        return toJpeg(photoCanvas)
      },
      stop() {
        stopped = true
        for (const track of stream.getTracks()) track.stop()
      },
    }
  }
}

const THIS_MACHINE = new Set(['127.0.0.1', 'localhost', '::1', '[::1]'])

export const CAMERA_DEVICE_SETTING = 'pb.booth.cameraDevice'

/** The camera this booth was told to use (an operator's choice, kept for the next visits). */
export function rememberedCamera(): string | null {
  try {
    return window.localStorage.getItem(CAMERA_DEVICE_SETTING)
  } catch {
    return null
  }
}

export function rememberCamera(deviceId: string | null): void {
  try {
    if (deviceId) window.localStorage.setItem(CAMERA_DEVICE_SETTING, deviceId)
    else window.localStorage.removeItem(CAMERA_DEVICE_SETTING)
  } catch {
    // Storage may be unavailable; the booth then uses the browser's own default camera.
  }
}

/**
 * The camera of this booth. Opened on the booth PC itself: the PC's camera through the browser.
 * Opened on another device (a TV on the LAN): the booth PC's camera, through the server. The
 * drawn `TestCamera` above is never chosen here — automated tests hand it to a screen directly —
 * so a booth can never quietly photograph generated pictures.
 */
export function chooseCamera(hostname: string = window.location.hostname): CameraSource {
  return THIS_MACHINE.has(hostname) ? new BrowserCamera() : new PcCamera()
}