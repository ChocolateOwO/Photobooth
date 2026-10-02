import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { expect, test, type Page } from './support/fixtures'

import { fixturesDir, pairAndSignIn, profileRow } from './support/admin'

// These specs share the e2e instance with admin.spec.ts and build on each other's data.
test.describe.configure({ mode: 'serial' })

// Exactly the approved templates, in the order the API returns them.
const LAYOUTS = [
  { key: 'print_3x4', name: '3x4 print', label: '3×4', size: '900 × 1200 px', frame: 'Small print frame' },
  { key: 'print_4x6', name: '4x6 print (2x2 grid)', label: '4×6', size: '1200 × 1800 px', frame: 'Big print frame' },
  { key: 'strip_2x6', name: '2x6 photo strip', label: '2×6', size: '600 × 1800 px', frame: 'Strip frame' },
] as const

const STRIP = LAYOUTS[2]
const RENAMED_STRIP = 'Strip frame renamed'
const PROFILE = 'E2E Frames profile'

function frameRow(page: Page, name: string) {
  return page.getByTestId('frame-row').filter({ has: page.getByRole('heading', { name, exact: true }) })
}

function uploadDialog(page: Page) {
  return page.getByRole('dialog', { name: 'Add frame' })
}

async function uploadFrame(page: Page, layout: (typeof LAYOUTS)[number], file: string, name: string) {
  await page.getByRole('button', { name: 'Add frame' }).click()
  const dialog = uploadDialog(page)
  await dialog.getByLabel('Layout').selectOption(layout.key)
  await dialog.getByLabel('Frame name').fill(name)
  await dialog.getByLabel('Frame PNG file').setInputFiles(join(fixturesDir, file))
  await dialog.getByRole('button', { name: 'Upload frame' }).click()
}

async function closeMessage(page: Page, name: string) {
  const message = page.getByRole('alertdialog', { name })
  await expect(message).toBeVisible()
  await message.getByRole('button', { name: 'Close' }).click()
  await expect(message).toHaveCount(0)
}

test('the frame manager lists compact layout rows with specifications on request', async ({ page }) => {
  await pairAndSignIn(page)
  await page.getByRole('link', { name: 'Frames' }).first().click()
  await expect(page.getByRole('heading', { name: 'Frames', exact: true })).toBeVisible()
  await expect(
    page.getByText(
      'Design frames in your own software, then upload the finished PNG here. This app never edits your file.',
    ),
  ).toBeVisible()

  const rows = page.getByTestId('layout-row')
  await expect(rows).toHaveCount(3)
  for (const [index, layout] of LAYOUTS.entries()) {
    const row = rows.nth(index)
    await expect(row).toContainText(layout.name)
    await expect(row).toContainText(layout.size)
    // One compact line per layout.
    expect((await row.boundingBox())?.height ?? 999).toBeLessThanOrEqual(64)
  }
  // Specifications, downloads and upload forms are not on the page itself.
  await expect(page.getByText(/File: PNG with transparency/)).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Download blank canvas' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Download guide image' })).toHaveCount(0)
  await expect(page.getByLabel('Frame PNG file')).toHaveCount(0)

  for (const layout of LAYOUTS) {
    await page.getByRole('button', { name: `Details of ${layout.name}` }).click()
    const details = page.getByRole('dialog', { name: `${layout.name}: specification` })
    await expect(details.getByText(/File: PNG with transparency/)).toBeVisible()
    await expect(details.getByText('300 DPI', { exact: true })).toBeVisible()
    await expect(details.getByRole('table', { name: 'Photo slot coordinates (px)' })).toBeVisible()
    await expect(details.getByRole('link', { name: 'Download guide image' })).toHaveAttribute(
      'href',
      `/api/templates/${layout.key}/guide.png`,
    )
    await page.keyboard.press('Escape')
    await expect(details).toHaveCount(0)
    // The guide really downloads from the running backend.
    const guide = await page.request.get(`/api/templates/${layout.key}/guide.png`)
    expect(guide.status()).toBe(200)
    expect(guide.headers()['content-type']).toBe('image/png')
  }

  await page.getByRole('button', { name: `Preview of ${STRIP.name}` }).click()
  const preview = page.getByRole('dialog', { name: `${STRIP.name}: layout guide` })
  await expect(preview.getByRole('img')).toHaveCount(1)
  await expect
    .poll(() => preview.getByRole('img').evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBe(600)
  // The dialog is centred in the window.
  const box = await preview.boundingBox()
  const viewport = page.viewportSize()
  expect(Math.abs((box?.x ?? 0) + (box?.width ?? 0) / 2 - (viewport?.width ?? 0) / 2)).toBeLessThan(4)
  await page.keyboard.press('Escape')

  // No drawing or design tool anywhere.
  await expect(page.locator('canvas')).toHaveCount(0)
})

test('the catalogue filters are compact pills with a distinct selected state', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  const pills = page.getByRole('group', { name: 'Show' })
  const all = pills.getByRole('button', { name: 'All' })
  const uploaded = pills.getByRole('button', { name: 'Uploaded' })
  await expect(all).toHaveAttribute('aria-pressed', 'true')
  const allBox = await all.boundingBox()
  expect(allBox?.height ?? 0).toBeGreaterThanOrEqual(44) // a real touch target...
  expect(allBox?.height ?? 99).toBeLessThanOrEqual(48) // ...but slim, not a big rectangle
  expect(await all.evaluate((el) => parseFloat(getComputedStyle(el).borderRadius))).toBeGreaterThanOrEqual(22)
  const selectedBg = await all.evaluate((el) => getComputedStyle(el).backgroundColor)
  const otherBg = await uploaded.evaluate((el) => getComputedStyle(el).backgroundColor)
  expect(selectedBg).toBe('rgb(47, 111, 214)') // --pb-color-primary
  expect(otherBg).not.toBe(selectedBg)
  // All pills sit on one row.
  const tops = await pills.getByRole('button').evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().top)))
  expect(new Set(tops).size).toBe(1)

  await all.focus()
  await page.keyboard.press('ArrowRight')
  await expect(pills.getByRole('button', { name: '3×4' })).toBeFocused()
  await expect(pills.getByRole('button', { name: '3×4' })).toHaveAttribute('aria-pressed', 'true')
  await page.keyboard.press('Home')
  await expect(all).toHaveAttribute('aria-pressed', 'true')
})

test('upload a valid frame for each of the three layouts from one Add frame dialog', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  for (const layout of LAYOUTS) {
    await uploadFrame(page, layout, `frame_${layout.key}.png`, layout.frame)
    const done = page.getByRole('alertdialog', { name: 'Frame added' })
    await expect(done).toContainText(`${layout.frame} was added.`)
    await done.getByRole('button', { name: 'Close' }).click()
    const row = frameRow(page, layout.frame)
    await expect(row.getByText(`${layout.label} · ${layout.size}`)).toBeVisible()
    await expect(row.getByText('Uploaded')).toBeVisible()
    // One rendered thumbnail only, loaded from the server.
    await expect(row.getByRole('img')).toHaveCount(1)
    await expect
      .poll(
        () => row.getByRole('img', { name: `${layout.frame} sample output` }).evaluate((img: HTMLImageElement) => img.naturalWidth),
        { timeout: 20_000 },
      )
      .toBeGreaterThan(0)
    expect((await row.boundingBox())?.height ?? 999).toBeLessThanOrEqual(110)
  }
})

test('a frame preview opens one large image, from the button or the thumbnail', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  const row = frameRow(page, STRIP.frame)
  await row.getByRole('button', { name: `Preview ${STRIP.frame}` }).click()
  let dialog = page.getByRole('dialog', { name: STRIP.frame })
  await expect(dialog.getByRole('img')).toHaveCount(1)
  await expect
    .poll(() => dialog.getByRole('img').evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 20_000 })
    .toBeGreaterThan(0)
  expect((await dialog.getByRole('img').boundingBox())?.height ?? 0).toBeGreaterThan(300)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)

  // The whole thumbnail is a click target for the large preview.
  await row.locator('button[aria-hidden="true"]').click()
  dialog = page.getByRole('dialog', { name: STRIP.frame })
  await expect(dialog.getByRole('img')).toHaveCount(1)
  await dialog.getByRole('button', { name: 'Close' }).click()
})

test('invalid frames are refused with a plain reason inside the upload dialog', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  const layout = STRIP // the 2x6 strip, so the expected size in the message is 600 x 1800
  const dialog = uploadDialog(page)

  await uploadFrame(page, layout, 'frame_wrong_size.png', 'Wrong size')
  await expect(dialog.getByRole('alert')).toContainText('exactly 600 x 1800 px')
  await page.keyboard.press('Escape')

  await uploadFrame(page, layout, 'frame_opaque_slots.png', 'Opaque')
  await expect(dialog.getByRole('alert')).toContainText('Photo 1 area must be at least 95% transparent')

  // A JPEG is refused in the browser before it is sent.
  await dialog.getByLabel('Frame PNG file').setInputFiles(join(fixturesDir, 'frame_not_png.jpg'))
  await expect(dialog.getByRole('alert')).toContainText('The frame must be a PNG file.')
  await page.keyboard.press('Escape')

  // A frame of the wrong layout is refused too (3x4 file offered to the 2x6 layout).
  await uploadFrame(page, layout, 'frame_print_3x4.png', 'Wrong layout')
  await expect(dialog.getByRole('alert')).toContainText('exactly 600 x 1800 px')
  await page.keyboard.press('Escape')

  await expect(frameRow(page, 'Wrong size')).toHaveCount(0)
  await expect(frameRow(page, 'Opaque')).toHaveCount(0)
})

async function boothFrameNames(page: Page): Promise<string[]> {
  const menu = (await (await page.request.get('/api/booth/frames')).json()) as { frames: { name: string }[] }
  return menu.frames.map((frame) => frame.name)
}

function sizePill(page: Page, label: string) {
  return page.getByRole('group', { name: 'Photo sizes available' }).getByRole('button', { name: new RegExp(`^${label}`) })
}

test('uploads reach every profile offering their size, without editing the profile', async ({ page }) => {
  await pairAndSignIn(page)
  // The active profile (admin.spec's copy) offers every size: every upload is already offered,
  // although no profile was edited after the uploads.
  const offered = await boothFrameNames(page)
  for (const layout of LAYOUTS) expect(offered).toContain(layout.frame)

  // A new upload of an offered size appears at the booth at once.
  await page.goto('/admin/frames')
  await uploadFrame(page, STRIP, `frame_${STRIP.key}_v2.png`, 'Late strip')
  await closeMessage(page, 'Frame added')
  expect(await boothFrameNames(page)).toContain('Late strip')

  // A new profile offers every size, so every frame; the counts include the uploads.
  await page.goto('/admin')
  await page.getByRole('link', { name: 'New profile' }).click()
  await page.getByLabel('Profile name').fill(PROFILE)
  await page.getByLabel('Title', { exact: true }).fill('Frames please')
  await expect(page.getByTestId('available-frames-summary')).toHaveText('13 frames available to participants.')
  await expect(sizePill(page, '2×6')).toHaveAccessibleName('2×6, 5 frames')
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page).toHaveURL(/\/admin\/profiles\/[0-9a-f-]{36}$/)
  await page.reload()
  for (const layout of LAYOUTS) await expect(sizePill(page, layout.label)).toHaveAttribute('aria-pressed', 'true')

  // Deleting the upload removes it from the booth, again without touching a profile.
  await page.goto('/admin/frames')
  await frameRow(page, 'Late strip').getByRole('button', { name: 'Delete Late strip' }).click()
  await page.getByRole('alertdialog', { name: 'Delete Late strip?' }).getByRole('button', { name: 'Delete frame' }).click()
  await expect(frameRow(page, 'Late strip')).toHaveCount(0)
  expect(await boothFrameNames(page)).not.toContain('Late strip')
})
test('an offered frame can be replaced and renamed, and the booth follows', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  const layout = STRIP
  const row = frameRow(page, layout.frame)

  // Its size is offered by the profiles, so it shows who offers it; deleting asks first.
  await expect(row.getByTestId('frame-usage')).toContainText(PROFILE)
  await row.getByRole('button', { name: `Delete ${layout.frame}` }).click()
  const confirm = page.getByRole('alertdialog', { name: `Delete ${layout.frame}?` })
  await expect(confirm.getByRole('button', { name: 'Cancel' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(row).toHaveCount(1)

  // Replacing the file keeps it offered, and the page shows the new file
  // (a new versioned URL whose bytes are the replacement), never the cached old image.
  const thumb = row.getByRole('img', { name: `${layout.frame} sample output` })
  const oldSrc = (await thumb.getAttribute('src')) ?? ''
  await row.getByLabel(`New PNG file for ${layout.frame}`).setInputFiles(
    join(fixturesDir, `frame_${layout.key}_v2.png`),
  )
  await closeMessage(page, 'File replaced')
  await expect(thumb).not.toHaveAttribute('src', oldSrc)
  const version = ((await thumb.getAttribute('src')) ?? '').split('?v=')[1] ?? 'missing'
  const frameId = /frames\/([0-9a-f-]{36})\//.exec(oldSrc)?.[1] ?? 'missing'
  const served = await page.request.get(`/api/admin/frames/${frameId}/content?v=${version}`)
  expect(served.status()).toBe(200)
  const replacement = readFileSync(join(fixturesDir, `frame_${layout.key}_v2.png`))
  expect(Buffer.compare(await served.body(), replacement)).toBe(0)
  await expect
    .poll(() => thumb.evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 20_000 })
    .toBeGreaterThan(0)

  await row.getByRole('button', { name: `Rename ${layout.frame}` }).click()
  const rename = page.getByRole('dialog', { name: `Rename ${layout.frame}` })
  await rename.getByLabel('Frame name').fill(RENAMED_STRIP)
  await rename.getByRole('button', { name: 'Save name' }).click()
  await expect(frameRow(page, RENAMED_STRIP)).toHaveCount(1)
  const names = await boothFrameNames(page)
  expect(names).toContain(RENAMED_STRIP)
  expect(names).not.toContain(layout.frame)
})

test('an unused frame can be deleted', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  const layout = LAYOUTS[1]
  await uploadFrame(page, layout, `frame_${layout.key}_v2.png`, 'Spare frame')
  await closeMessage(page, 'Frame added')
  const row = frameRow(page, 'Spare frame')
  await expect(row).toHaveCount(1)
  await row.getByRole('button', { name: 'Delete Spare frame' }).click()
  await page.getByRole('alertdialog', { name: 'Delete Spare frame?' }).getByRole('button', { name: 'Delete frame' }).click()
  await expect(frameRow(page, 'Spare frame')).toHaveCount(0)
})

test('a busy sample preview is retried instead of staying broken', async ({ page }) => {
  // The render queue answers 503 while it is full; the first two answers here are 503.
  let refused = 0
  await page.route('**/api/admin/frames/*/preview/1.jpg*', async (route) => {
    if (refused < 2) {
      refused += 1
      await route.fulfill({ status: 503, headers: { 'Retry-After': '2' }, body: 'busy' })
      return
    }
    await route.continue()
  })
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  const row = frameRow(page, LAYOUTS[0].frame)
  await expect
    .poll(
      () =>
        row
          .getByRole('img', { name: `${LAYOUTS[0].frame} sample output` })
          .evaluate((img: HTMLImageElement) => img.naturalWidth),
      { timeout: 20_000 },
    )
    .toBeGreaterThan(0)
  expect(refused).toBe(2)
})

test('unauthorized browsers get no frame data', async ({ browser }) => {
  const context = await browser.newContext({ baseURL: 'http://127.0.0.1:5192' })
  const page = await context.newPage()
  try {
    await page.goto('/admin/frames')
    await expect(page.getByRole('heading', { name: 'Kiosk not paired' })).toBeVisible()
    expect((await page.request.get('/api/admin/frames')).status()).toBe(401)
    expect((await page.request.post('/api/admin/frames')).status()).toBe(401)
  } finally {
    await context.close()
  }
})

test('the frame manager works on a narrow phone screen', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 })
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  await expect(page.getByRole('heading', { name: 'Frames', exact: true })).toBeVisible()
  const add = page.getByRole('button', { name: 'Add frame' })
  const box = await add.boundingBox()
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
  expect(box?.width ?? 0).toBeLessThanOrEqual(360)
  // The pill row scrolls sideways inside itself instead of widening the page.
  const pills = page.getByRole('group', { name: 'Show' })
  const tops = await pills.getByRole('button').evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().top)))
  expect(new Set(tops).size).toBe(1)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1) // no sideways scrolling
  await add.click()
  await expect(uploadDialog(page)).toBeVisible()
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
  ).toBeLessThanOrEqual(1)
})

test('frames and selections survive a backend restart @after-restart', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  await expect(frameRow(page, RENAMED_STRIP)).toHaveCount(1)
  await expect(frameRow(page, LAYOUTS[1].frame)).toHaveCount(1)
  // Thumbnails load lazily: bring the row into view.
  await frameRow(page, RENAMED_STRIP).scrollIntoViewIfNeeded()
  await expect
    .poll(
      () =>
        frameRow(page, RENAMED_STRIP)
          .getByRole('img', { name: `${RENAMED_STRIP} sample output` })
          .evaluate((img: HTMLImageElement) => img.naturalWidth),
      { timeout: 20_000 },
    )
    .toBeGreaterThan(0)

  await page.goto('/admin')
  await profileRow(page, PROFILE).getByRole('link', { name: `Edit ${PROFILE}`, exact: true }).click()
  for (const layout of LAYOUTS) await expect(sizePill(page, layout.label)).toHaveAttribute('aria-pressed', 'true')
  expect(await boothFrameNames(page)).toContain(RENAMED_STRIP)
  await page.getByLabel('Title', { exact: true }).fill('Frames after restart')
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByRole('alertdialog', { name: 'Saved' })).toContainText('Profile saved successfully.')
})
