import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  BrowserCamera,
  CAMERA_DEVICE_SETTING,
  CameraError,
  PcCamera,
  TestCamera,
  cameraMessage,
  chooseCamera,
  rememberCamera,
  rememberedCamera,
} from './camera'

/** The booth's camera port: which camera a booth gets, and how each refusal is explained. */

class StubStream {
  getTracks() {
    return []
  }
  getVideoTracks() {
    return []
  }
}

function withMediaDevices(getUserMedia: unknown, devices: MediaDeviceInfo[] = []) {
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia, enumerateDevices: async () => devices },
  })
}

beforeEach(() => {
  ;(globalThis as { MediaStream?: unknown }).MediaStream = StubStream
  localStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
  Reflect.deleteProperty(navigator, 'mediaDevices')
})

describe('the booth camera', () => {
  it("on another device (a TV on the Wi-Fi) is the booth PC's camera", () => {
    expect(chooseCamera('192.168.1.135')).toBeInstanceOf(PcCamera)
    expect(chooseCamera('127.0.0.1')).toBeInstanceOf(BrowserCamera)
    expect(chooseCamera('localhost')).toBeInstanceOf(BrowserCamera)
  })

  it("says 'missing' when the PC has no camera to give, before any countdown", async () => {
    const fetcher = vi.fn(async () => new Response(null, { status: 503 }))
    await expect(new PcCamera(fetcher).open()).rejects.toMatchObject({ problem: 'missing' })
    expect(fetcher).toHaveBeenCalledWith('/api/booth/camera/frame.jpg?preview=true')
  })

  it("says 'lost' when the PC can not be reached", async () => {
    const fetcher = vi.fn(async () => {
      throw new TypeError('network')
    })
    await expect(new PcCamera(fetcher).open()).rejects.toMatchObject({ problem: 'lost' })
  })

  it("is always the machine's own camera; the drawn one can not be asked for", () => {
    expect(chooseCamera().kind).toBe('browser')
    expect(chooseCamera()).toBeInstanceOf(BrowserCamera)
    // Nothing in an address or left in storage can turn a booth into generated pictures.
    localStorage.setItem('pb.booth.camera', 'test')
    window.history.replaceState(null, '', '/booth?camera=test')
    expect(chooseCamera().kind).toBe('browser')
  })

  it("remembers which of the machine's cameras the booth should use", () => {
    expect(rememberedCamera()).toBeNull()
    rememberCamera('usb-cam')
    expect(localStorage.getItem(CAMERA_DEVICE_SETTING)).toBe('usb-cam')
    expect(rememberedCamera()).toBe('usb-cam')
    rememberCamera(null)
    expect(rememberedCamera()).toBeNull()
  })

  it('says plainly what went wrong, in words a guest can act on', () => {
    expect(cameraMessage('denied')).toContain('Allow it in the browser')
    expect(cameraMessage('missing')).toContain('No camera is connected')
    expect(cameraMessage('in-use')).toContain('Another program is using the camera')
    expect(cameraMessage('lost')).toContain('disconnected')
    expect(cameraMessage('insecure')).toContain('127.0.0.1')
  })

  it('turns each browser refusal into the matching problem', async () => {
    const cases: [string, string][] = [
      ['NotAllowedError', 'denied'],
      ['NotFoundError', 'missing'],
      ['NotReadableError', 'in-use'],
      ['SomethingElseError', 'failed'],
    ]
    for (const [name, problem] of cases) {
      withMediaDevices(() => {
        const error = new Error('refused')
        error.name = name
        return Promise.reject(error)
      })
      await expect(new BrowserCamera().open()).rejects.toMatchObject({ problem })
    }
  })

  it('explains that a camera needs the booth page itself, not a page with no camera access', async () => {
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: undefined })
    await expect(new BrowserCamera().open()).rejects.toBeInstanceOf(CameraError)
    await expect(new BrowserCamera().open()).rejects.toMatchObject({ problem: 'insecure' })
  })

  it('lists the cameras of this machine, naming the unnamed ones', async () => {
    withMediaDevices(undefined, [
      { kind: 'videoinput', deviceId: 'a', label: 'Front' },
      { kind: 'audioinput', deviceId: 'b', label: 'Mic' },
      { kind: 'videoinput', deviceId: 'c', label: '' },
    ] as MediaDeviceInfo[])
    expect(await new BrowserCamera().devices()).toEqual([
      { id: 'a', label: 'Front' },
      { id: 'c', label: 'Camera 2' },
    ])
  })

  it('the drawn test camera gives a different photo every time and stops cleanly', async () => {
    // jsdom draws nothing, so the canvas is stood in for: whatever was last drawn becomes the
    // photo, which is exactly what the real camera does with the picture on screen.
    let drawn = ''
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      fillRect: () => undefined,
      fillText: (text: string) => {
        if (/^\d+$/.test(text)) drawn = text
      },
      drawImage: () => undefined,
      set fillStyle(_value: string) {},
      set font(_value: string) {},
      set textAlign(_value: string) {},
    } as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((callback) => {
      callback(new Blob([`frame-${drawn}`], { type: 'image/jpeg' }))
    })
    const view = await new TestCamera().open()
    expect(view.live()).toBe(true)
    const photos = [await view.photo(), await view.photo(), await view.photo()]
    const contents = await Promise.all(photos.map((photo) => photo.text()))
    expect(new Set(contents).size).toBe(3) // three different pictures, as a real camera gives
    for (const photo of photos) expect(photo.type).toBe('image/jpeg')
    view.stop()
    expect(view.live()).toBe(false)
    await expect(view.photo()).rejects.toMatchObject({ problem: 'lost' })
  })
})
