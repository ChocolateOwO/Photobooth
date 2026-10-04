import { expect, test, type Page } from './support/fixtures'

import { PERSISTED, pairAndSignIn, profileRow } from './support/admin'

/**
 * Phase 9, as a guest lives it: the photos are taken, the guest adds a filter and stickers,
 * moves them with a finger, changes their mind (undo, start again), confirms, and the finished
 * photos come out the way the booth showed them.
 */

test.describe.configure({ mode: 'serial' })

/** Prepared by capture.spec: one second per photo, every size offered. */
const QUICK = 'E2E Capture'

async function activate(page: Page, name: string): Promise<void> {
  await page.goto('/admin')
  const row = profileRow(page, name)
  const button = row.getByRole('button', { name: `Activate ${name}`, exact: true })
  if (await button.isEnabled()) await button.click()
  await expect(row.getByText('Active', { exact: true })).toBeVisible()
}

async function takePhotos(page: Page, size: string): Promise<void> {
  await page.goto('/booth/frames')
  await page.getByRole('tab', { name: size }).click()
  const slide = page.getByTestId('frame-slide').filter({ hasText: 'Midnight' }).first()
  await slide.scrollIntoViewIfNeeded()
  await slide.getByRole('button', { name: 'Use this frame' }).click()
  await page
    .getByRole('dialog', { name: 'Use this frame?' })
    .getByRole('button', { name: 'Start with this frame' })
    .click()
  await expect(page.getByRole('heading', { name: 'All photos taken' })).toBeVisible({
    timeout: 60_000,
  })
  await page.getByRole('button', { name: 'These are good' }).click()
  await expect(page).toHaveURL(/\/booth\/decorate$/)
  await expect(page.getByRole('heading', { name: 'Decorate your photos' })).toBeVisible()
}

async function visit(page: Page): Promise<{ id: string; state: string } | null> {
  return (await (await page.request.get('/api/booth/sessions/current')).json()) as never
}

/** Every picture inside the preview has really loaded (an <image> that failed draws nothing). */
async function previewLoaded(page: Page): Promise<void> {
  await expect
    .poll(() =>
      page.getByTestId('decorated-photo').first().evaluate(async (svg) => {
        const sources = Array.from(svg.querySelectorAll('image'), (node) => node.getAttribute('href'))
        const loaded = await Promise.all(
          sources.map(
            (src) =>
              new Promise<boolean>((resolve) => {
                const img = new Image()
                img.onload = () => resolve(img.naturalWidth > 0)
                img.onerror = () => resolve(false)
                img.src = src ?? ''
              }),
          ),
        )
        return loaded.every(Boolean)
      }),
    )
    .toBe(true)
}

/**
 * How far apart two pictures are, in the browser: both are drawn into the same small grid and
 * compared cell by cell. Returns the mean and the 98th-percentile cell difference (0..255).
 *
 * Measured on Dummy (2026-10-01): a correct preview scores mean 1.5-2, p98 13-23. The largest
 * single cells (up to ~75) sit on sharp edges such as the frame's moon, where a 180-pixel-wide
 * screenshot and the 600-pixel print are resampled differently, so the largest cell is not a
 * useful bound. Real mistakes score far higher: a missing sticker p98 107, a mirrored preview
 * p98 107, the wrong filter mean 14.6 and p98 67.
 */
async function difference(page: Page, a: string, b: string): Promise<{ mean: number; p98: number }> {
  return page.evaluate(
    async ([first, second]) => {
      const W = 40
      const H = 120
      async function cells(src: string): Promise<Uint8ClampedArray> {
        const img = new Image()
        img.src = src
        await img.decode()
        const canvas = document.createElement('canvas')
        canvas.width = W
        canvas.height = H
        const context = canvas.getContext('2d') as CanvasRenderingContext2D
        context.imageSmoothingQuality = 'high'
        context.drawImage(img, 0, 0, W, H)
        return context.getImageData(0, 0, W, H).data
      }
      const [x, y] = await Promise.all([cells(first), cells(second)])
      const found: number[] = []
      for (let i = 0; i < x.length; i += 4) {
        const column = (i / 4) % W
        const row = Math.floor(i / 4 / W)
        // The outer ring is left out: the preview's rounded corners show the page behind them.
        if (column === 0 || row === 0 || column === W - 1 || row === H - 1) continue
        const d =
          (Math.abs((x[i] ?? 0) - (y[i] ?? 0)) +
            Math.abs((x[i + 1] ?? 0) - (y[i + 1] ?? 0)) +
            Math.abs((x[i + 2] ?? 0) - (y[i + 2] ?? 0))) /
          3
        found.push(d)
      }
      found.sort((p, q) => p - q)
      const mean = found.reduce((sum, d) => sum + d, 0) / found.length
      return { mean, p98: found[Math.floor(found.length * 0.98)] ?? 255 }
    },
    [a, b] as const,
  )
}

test('a guest decorates a 2×6 and the finished strips match what the booth showed', async ({
  page,
}) => {
  test.setTimeout(150_000)
  await pairAndSignIn(page)
  await activate(page, QUICK)
  await takePhotos(page, '2×6')

  const strips = page.getByTestId('decorated-photo')
  await expect(strips).toHaveCount(2)
  await previewLoaded(page)

  // A filter, then stickers: one on each strip.
  await page.getByRole('tab', { name: 'Filters' }).click()
  await page.getByRole('radio', { name: /Sepia/ }).click()
  await expect(page.getByRole('radio', { name: /Sepia/ })).toHaveAttribute('aria-checked', 'true')
  await page.getByRole('tab', { name: 'Stickers' }).click()
  await page.getByRole('button', { name: 'Add Heart' }).click()
  await expect(strips.nth(0).getByTestId('placed-sticker')).toHaveCount(1)

  // A finger drags the heart down and to the left; the buttons make it bigger and turn it.
  const heart = strips.nth(0).getByTestId('placed-sticker').first()
  const box = (await heart.boundingBox()) as { x: number; y: number; width: number; height: number }
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 - 20, box.y + box.height / 2 + 80, { steps: 8 })
  await page.mouse.up()
  const moved = (await heart.boundingBox()) as { x: number; y: number; width: number; height: number }
  expect(moved.y).toBeGreaterThan(box.y + 40)

  // Its Resize handle (on its corner) makes it bigger in place, keeping its shape.
  const handles = strips.nth(0).getByTestId('sticker-handles')
  await expect(handles.getByRole('button')).toHaveCount(3)
  const resize = (await handles
    .getByRole('button', { name: 'Resize sticker' })
    .boundingBox()) as { x: number; y: number; width: number; height: number }
  const grab = { x: resize.x + resize.width / 2, y: resize.y + resize.height / 2 }
  const centre = { x: moved.x + moved.width / 2, y: moved.y + moved.height / 2 }
  await page.mouse.move(grab.x, grab.y)
  await page.mouse.down()
  await page.mouse.move(
    centre.x + (grab.x - centre.x) * 1.5,
    centre.y + (grab.y - centre.y) * 1.5,
    { steps: 8 },
  )
  await page.mouse.up()
  const grown = (await heart.boundingBox()) as { x: number; y: number; width: number; height: number }
  expect(grown.width).toBeGreaterThan(moved.width * 1.3)
  expect(grown.width / grown.height).toBeCloseTo(moved.width / moved.height, 1) // the same shape
  expect(grown.x + grown.width / 2).toBeCloseTo(centre.x, -1) // in place
  expect(grown.y + grown.height / 2).toBeCloseTo(centre.y, -1)

  // A second sticker on the same strip goes again with its Remove handle.
  await page.getByRole('button', { name: 'Add Star' }).click()
  await expect(strips.nth(0).getByTestId('placed-sticker')).toHaveCount(2)
  await handles.getByRole('button', { name: 'Remove sticker' }).click()
  await expect(strips.nth(0).getByTestId('placed-sticker')).toHaveCount(1)
  await expect(strips.nth(0).getByTestId('sticker-handles')).toHaveCount(0)

  // The second strip gets a star.
  await strips.nth(1).click({ position: { x: 10, y: 10 } })
  await page.getByRole('button', { name: 'Add Star' }).click()
  await expect(strips.nth(1).getByTestId('placed-sticker')).toHaveCount(1)

  // Undo takes the star away again; Start again clears everything; Undo brings it all back.
  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(strips.nth(1).getByTestId('placed-sticker')).toHaveCount(0)
  await page.getByRole('button', { name: 'Start again' }).click()
  await expect(page.getByTestId('placed-sticker')).toHaveCount(0)
  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(strips.nth(0).getByTestId('placed-sticker')).toHaveCount(1)
  await page.getByRole('tab', { name: 'Filters' }).click()
  await expect(page.getByRole('radio', { name: /Sepia/ })).toHaveAttribute('aria-checked', 'true')

  // Nothing chosen any more, so the preview shows exactly what will be made.
  await strips.nth(0).click({ position: { x: 4, y: 4 } })
  await expect(page.locator('[data-selected]')).toHaveCount(0)
  await previewLoaded(page)
  const previews = [
    `data:image/png;base64,${(await strips.nth(0).screenshot()).toString('base64')}`,
    `data:image/png;base64,${(await strips.nth(1).screenshot()).toString('base64')}`,
  ]

  // Confirm: the photos are made once, and the take-home screen follows. Even with a sticker
  // chosen, its handles leave the picture as soon as the guest is asked to confirm.
  await strips.nth(0).getByTestId('placed-sticker').first().click()
  await expect(strips.nth(0).getByTestId('sticker-handles')).toHaveCount(1)
  await page.getByRole('button', { name: 'Finish' }).click()
  const dialog = page.getByRole('dialog', { name: 'Finish your photos?' })
  await expect(page.getByTestId('sticker-handles')).toHaveCount(0)
  await expect(page.getByTestId('sticker-outline')).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Keep decorating' }).click()
  await expect(dialog).toBeHidden()
  await page.getByRole('button', { name: 'Finish' }).click()
  await dialog.getByRole('button', { name: 'Make my photos' }).click()
  await expect(page).toHaveURL(/\/booth\/done$/, { timeout: 30_000 })
  await expect(page.getByTestId('finished-photos').getByRole('img')).toHaveCount(2)
  expect((await visit(page))?.state).toBe('delivered')

  // Parity: the server's strips look like the booth's preview: the same filter, frame and
  // stickers in the same places, compared cell by cell.
  const finished = page.getByTestId('finished-photos').getByRole('img')
  for (const index of [0, 1]) {
    const src = (await finished.nth(index).getAttribute('src')) ?? ''
    const { mean, p98 } = await difference(page, previews[index] ?? '', src)
    expect(mean, `strip ${index + 1} mean difference`).toBeLessThan(4)
    expect(p98, `strip ${index + 1} 98th-percentile cell`).toBeLessThan(40)
  }
  await page.getByRole('button', { name: 'Done' }).click()
  await expect(page).toHaveURL(/\/booth$/)
})

test('a guest who wants no decorations simply finishes', async ({ page }) => {
  await pairAndSignIn(page)
  await takePhotos(page, '3×4')
  await page.getByRole('button', { name: 'Finish' }).click()
  await page
    .getByRole('dialog', { name: 'Finish your photos?' })
    .getByRole('button', { name: 'Make my photos' })
    .click()
  await expect(page).toHaveURL(/\/booth\/done$/, { timeout: 30_000 })
  await expect(page.getByTestId('finished-photos').getByRole('img')).toHaveCount(1)
  // A reload of the take-home screen stays there; the decorate screen is behind the guest.
  await page.goto('/booth/decorate')
  await expect(page).toHaveURL(/\/booth\/done$/)
  await page.getByRole('button', { name: 'Done' }).click()
})

test.describe('touchscreen', () => {
  test.use({ hasTouch: true })

  test('a finger resizes a sticker by its corner handle and removes it with another', async ({
    page,
  }) => {
    test.setTimeout(120_000)
    await pairAndSignIn(page)
    await takePhotos(page, '3×4')
    await page.getByRole('button', { name: 'Add Heart' }).click()
    const photo = page.getByTestId('decorated-photo')
    const heart = photo.getByTestId('placed-sticker')
    const before = (await heart.boundingBox()) as { x: number; y: number; width: number; height: number }
    const handle = (await photo
      .getByRole('button', { name: 'Resize sticker' })
      .boundingBox()) as { x: number; y: number; width: number; height: number }
    const from = { x: handle.x + handle.width / 2, y: handle.y + handle.height / 2 }
    const centre = { x: before.x + before.width / 2, y: before.y + before.height / 2 }
    const cdp = await page.context().newCDPSession(page)
    const touch = (p: { x: number; y: number }) => [{ x: Math.round(p.x), y: Math.round(p.y), id: 1 }]
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: touch(from) })
    for (let step = 1; step <= 8; step++) {
      const f = 1 + (0.4 * step) / 8 // 40 % farther from the centre
      await cdp.send('Input.dispatchTouchEvent', {
        type: 'touchMove',
        touchPoints: touch({
          x: centre.x + (from.x - centre.x) * f,
          y: centre.y + (from.y - centre.y) * f,
        }),
      })
    }
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
    const after = (await heart.boundingBox()) as { width: number; height: number }
    expect(after.width).toBeGreaterThan(before.width * 1.2)
    expect(after.width / after.height).toBeCloseTo(before.width / before.height, 1)

    const remove = (await photo
      .getByRole('button', { name: 'Remove sticker' })
      .boundingBox()) as { x: number; y: number; width: number; height: number }
    const tap = { x: remove.x + remove.width / 2, y: remove.y + remove.height / 2 }
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: touch(tap) })
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
    await cdp.detach()
    await expect(heart).toHaveCount(0)

    await page.getByRole('button', { name: 'Finish' }).click()
    await page
      .getByRole('dialog', { name: 'Finish your photos?' })
      .getByRole('button', { name: 'Make my photos' })
      .click()
    await expect(page).toHaveURL(/\/booth\/done$/, { timeout: 30_000 })
    await page.getByRole('button', { name: 'Done' }).click()
  })
})

test('the event the later specs expect is active again', async ({ page }) => {
  await pairAndSignIn(page)
  await activate(page, PERSISTED.copy)
})
