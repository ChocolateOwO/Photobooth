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
  readonly kind: 'browser' | 'test'
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

/** Draws the current video picture at capture size, cropped to fill (never stretched). */
function drawCover(video: HTMLVideoElement, canvas: HTMLCanvasElement): void {
  const context = canvas.getContext('2d')
  if (!context) throw new CameraError('failed', 'this browser can not take photos')
  const width = video.videoWidth || CAPTURE_WIDTH
  const height = video.videoHeight || CAPTURE_HEIGHT
  const scale = Math.max(canvas.width / width, canvas.height / height)
  const drawWidth = width * scale
  const drawHeight = height * scale
  context.drawImage(
    video,
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
        drawCover(video, canvas)
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

export const TEST_CAMERA_SETTING = 'pb.booth.camera'

/**
 * `?camera=test` is remembered as the page loads, because the booth screen that needs the camera
 * is reached by navigation, long after that address has gone.
 */
export function rememberCameraPreference(
  search: string = typeof window === 'undefined' ? '' : window.location.search,
): void {
  try {
    const wanted = new URLSearchParams(search).get('camera')
    if (wanted) window.localStorage.setItem(TEST_CAMERA_SETTING, wanted)
  } catch {
    // Storage may be unavailable; the booth then simply uses the real camera.
  }
}

/**
 * Which camera this booth uses. The drawn test camera is only ever available in Dummy, and only
 * when it is asked for by `?camera=test` (kept for the rest of the visit in this browser).
 */
export function chooseCamera(
  instance: string,
  search: string = typeof window === 'undefined' ? '' : window.location.search,
): CameraSource {
  if (instance !== 'dummy') return new BrowserCamera()
  rememberCameraPreference(search)
  let wanted: string | null = null
  try {
    wanted = window.localStorage.getItem(TEST_CAMERA_SETTING)
  } catch {
    // Storage may be unavailable; the booth then simply uses the real camera.
  }
  return wanted === 'test' ? new TestCamera() : new BrowserCamera()
}
