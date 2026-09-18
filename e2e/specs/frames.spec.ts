import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { expect, test, type Page } from '@playwright/test'

import { fixturesDir, pairAndSignIn, profileRow } from './support/admin'

// These specs share the e2e instance with admin.spec.ts and build on each other's data.
test.describe.configure({ mode: 'serial' })

// Exactly the approved templates, in the order the API returns them.
const LAYOUTS = [
  { key: 'print_3x4', name: '3x4 print', size: '900 × 1200 px', frame: 'Small print frame' },
  { key: 'print_4x6', name: '4x6 print (2x2 grid)', size: '1200 × 1800 px', frame: 'Big print frame' },
  { key: 'strip_2x6', name: '2x6 photo strip', size: '600 × 1800 px', frame: 'Strip frame' },
] as const

const STRIP = LAYOUTS[2]
const RENAMED_STRIP = 'Strip frame renamed'
const PROFILE = 'E2E Frames profile'

function section(page: Page, layoutName: string) {
  return page
    .locator('section')
    .filter({ has: page.getByRole('heading', { name: layoutName, exact: true }) })
}

function frameCard(page: Page, name: string) {
  return page.getByTestId('frame-card').filter({ has: page.getByRole('heading', { name }) })
}

async function uploadFrame(page: Page, layout: (typeof LAYOUTS)[number], file: string, name: string) {
  const area = section(page, layout.name)
  await area.getByLabel('Frame name').fill(name)
  await area.getByLabel('Frame PNG file').setInputFiles(join(fixturesDir, file))
  await area.getByRole('button', { name: 'Upload frame' }).click()
}

test('the frame manager shows the specification and downloads for every layout', async ({ page }) => {
  await pairAndSignIn(page)
  await page.getByRole('link', { name: 'Frames' }).first().click()
  await expect(page.getByRole('heading', { name: 'Frames' })).toBeVisible()
  await expect(
    page.getByText(
      'Design frames in your own software, then upload the finished PNG here. This app never edits your file.',
    ),
  ).toBeVisible()

  for (const layout of LAYOUTS) {
    const area = section(page, layout.name)
    await expect(area.getByText(/File: PNG with transparency/)).toBeVisible()
    await expect(area.getByRole('link', { name: 'Download guide image' })).toHaveAttribute(
      'href',
      `/api/templates/${layout.key}/guide.png`,
    )
    // The guide really downloads from the running backend.
    const guide = await page.request.get(`/api/templates/${layout.key}/guide.png`)
    expect(guide.status()).toBe(200)
    expect(guide.headers()['content-type']).toBe('image/png')
  }
  // No drawing or design tool anywhere.
  await expect(page.locator('canvas')).toHaveCount(0)
})

test('upload a valid frame for each of the three layouts', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  for (const layout of LAYOUTS) {
    await uploadFrame(page, layout, `frame_${layout.key}.png`, layout.frame)
    const area = section(page, layout.name)
    await expect(area.getByRole('status')).toHaveText(`${layout.frame} was added.`)
    const card = frameCard(page, layout.frame)
    await expect(card.getByText(layout.size)).toBeVisible()
    // Both the uploaded file and a rendered sample output load from the server.
    for (const alt of [`${layout.frame} frame file`, `${layout.frame} sample output`]) {
      await expect
        .poll(
          () => card.getByRole('img', { name: alt }).evaluate((img: HTMLImageElement) => img.naturalWidth),
          { timeout: 20_000 },
        )
        .toBeGreaterThan(0)
    }
    await expect(card.getByText('Sample output with placeholder photos')).toBeVisible()
    expect(
      (await area.getByRole('button', { name: 'Upload frame' }).boundingBox())?.height ?? 0,
    ).toBeGreaterThanOrEqual(64)
  }
})

test('invalid frames are refused with a plain reason', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  const layout = STRIP // the 2x6 strip, so the expected size in the message is 600 x 1800
  const area = section(page, layout.name)

  await uploadFrame(page, layout, 'frame_wrong_size.png', 'Wrong size')
  await expect(area.getByRole('alert')).toContainText('exactly 600 x 1800 px')

  await uploadFrame(page, layout, 'frame_opaque_slots.png', 'Opaque')
  await expect(area.getByRole('alert')).toContainText(
    'Photo 1 area must be at least 95% transparent',
  )

  // A JPEG is refused in the browser before it is sent.
  await area.getByLabel('Frame name').fill('Not a png')
  await area.getByLabel('Frame PNG file').setInputFiles(join(fixturesDir, 'frame_not_png.jpg'))
  await expect(area.getByRole('alert')).toContainText('The frame must be a PNG file.')

  // A frame of the wrong layout is refused too (3x4 file offered to the 2x6 layout).
  await uploadFrame(page, layout, 'frame_print_3x4.png', 'Wrong layout')
  await expect(area.getByRole('alert')).toContainText('exactly 600 x 1800 px')

  await expect(frameCard(page, 'Wrong size')).toHaveCount(0)
  await expect(frameCard(page, 'Opaque')).toHaveCount(0)
})

test('choose a frame per enabled layout in a profile', async ({ page }) => {
  await pairAndSignIn(page)
  await page.getByRole('link', { name: 'New profile' }).click()
  await page.getByLabel('Profile name').fill(PROFILE)
  await page.getByLabel('Title', { exact: true }).fill('Frames please')
  for (const layout of LAYOUTS) {
    const checkbox = page.getByRole('checkbox', { name: layout.name, exact: true })
    if (!(await checkbox.isChecked())) {
      await checkbox.check()
    }
  }
  // Every enabled layout starts with a built-in frame of the same family.
  await expect(page.getByTestId('missing-frame-warning')).toHaveCount(0)
  for (const layout of LAYOUTS) {
    const select = page.getByLabel(`Frame for ${layout.name}`, { exact: true })
    await expect(select.locator('option:checked')).toHaveText('Midnight (Built-in)')
  }
  // Choosing no frame is still possible and clearly marked.
  await page.getByLabel(`Frame for ${LAYOUTS[0].name}`, { exact: true }).selectOption({ label: 'No frame selected' })
  await expect(page.getByTestId('missing-frame-warning')).toHaveCount(1)
  await expect(page.getByTestId('missing-frame-warning').first()).toContainText(
    `No frame selected for ${LAYOUTS[0].name}. Photos will print without a frame.`,
  )

  for (const layout of LAYOUTS) {
    await page.getByLabel(`Frame for ${layout.name}`, { exact: true }).selectOption({
      label: layout.frame,
    })
  }
  await expect(page.getByTestId('missing-frame-warning')).toHaveCount(0)
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page).toHaveURL(/\/admin\/profiles\/[0-9a-f-]{36}$/)

  await page.reload()
  for (const layout of LAYOUTS) {
    await expect(
      page.getByLabel(`Frame for ${layout.name}`, { exact: true }),
    ).toHaveValue(/[0-9a-f-]{36}/)
  }
  await expect(
    page.getByRole('img', { name: '3x4 print frame preview', exact: true }),
  ).toBeVisible()
})

test('a frame in use can not be deleted, but its file can be replaced', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  const layout = STRIP
  const area = section(page, layout.name)
  const card = frameCard(page, layout.frame)

  await card.getByRole('button', { name: `Delete ${layout.frame}` }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: `Delete ${layout.frame}?` })).toBeVisible()
  await dialog.getByRole('button', { name: 'Delete frame' }).click()
  await expect(area.getByRole('alert')).toContainText(PROFILE)
  await expect(card).toHaveCount(1)

  // Replacing the file keeps the profile selection working, and the page shows the new file
  // (a new versioned URL whose bytes are the replacement), never the cached old image.
  const fileImage = card.getByRole('img', { name: `${layout.frame} frame file` })
  const oldSrc = await fileImage.getAttribute('src')
  await card.getByLabel(`Replace file for ${layout.frame}`).setInputFiles(
    join(fixturesDir, `frame_${layout.key}_v2.png`),
  )
  await expect(fileImage).not.toHaveAttribute('src', oldSrc ?? '')
  const newSrc = (await fileImage.getAttribute('src')) ?? ''
  const served = await page.request.get(newSrc)
  expect(served.status()).toBe(200)
  const replacement = readFileSync(join(fixturesDir, `frame_${layout.key}_v2.png`))
  expect(Buffer.compare(await served.body(), replacement)).toBe(0)
  await expect(card.getByRole('img', { name: `${layout.frame} sample output` })).toHaveAttribute(
    'src',
    new RegExp(`\\?v=${newSrc.split('?v=')[1] ?? 'missing'}$`),
  )
  await expect
    .poll(
      () =>
        card
          .getByRole('img', { name: `${layout.frame} sample output` })
          .evaluate((img: HTMLImageElement) => img.naturalWidth),
      { timeout: 20_000 },
    )
    .toBeGreaterThan(0)

  await card.getByRole('button', { name: `Rename ${layout.frame}` }).click()
  await card.getByLabel('Frame name').fill(RENAMED_STRIP)
  await card.getByRole('button', { name: 'Save name' }).click()
  await expect(frameCard(page, RENAMED_STRIP)).toHaveCount(1)
})

test('an unused frame can be deleted', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  const layout = LAYOUTS[1]
  await uploadFrame(page, layout, `frame_${layout.key}_v2.png`, 'Spare frame')
  const card = frameCard(page, 'Spare frame')
  await expect(card).toHaveCount(1)
  await card.getByRole('button', { name: 'Delete Spare frame' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete frame' }).click()
  await expect(frameCard(page, 'Spare frame')).toHaveCount(0)
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
  const card = frameCard(page, LAYOUTS[0].frame)
  await expect
    .poll(
      () =>
        card
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
  await expect(page.getByRole('heading', { name: 'Frames' })).toBeVisible()
  const upload = section(page, LAYOUTS[0].name).getByRole('button', { name: 'Upload frame' })
  const box = await upload.boundingBox()
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(64)
  expect(box?.width ?? 0).toBeLessThanOrEqual(360)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1) // no sideways scrolling
})

test('frames and selections survive a backend restart @after-restart', async ({ page }) => {
  await pairAndSignIn(page)
  await page.goto('/admin/frames')
  await expect(frameCard(page, RENAMED_STRIP)).toHaveCount(1)
  await expect(frameCard(page, LAYOUTS[1].frame)).toHaveCount(1)
  await expect
    .poll(
      () =>
        frameCard(page, RENAMED_STRIP)
          .getByRole('img', { name: `${RENAMED_STRIP} frame file` })
          .evaluate((img: HTMLImageElement) => img.naturalWidth),
      { timeout: 20_000 },
    )
    .toBe(600)

  await page.goto('/admin')
  await profileRow(page, PROFILE).getByRole('link', { name: `Edit ${PROFILE}`, exact: true }).click()
  for (const layout of LAYOUTS) {
    await expect(
      page.getByLabel(`Frame for ${layout.name}`, { exact: true }),
    ).toHaveValue(/[0-9a-f-]{36}/)
  }
  await expect(page.getByTestId('missing-frame-warning')).toHaveCount(0)
  await page.getByLabel('Title', { exact: true }).fill('Frames after restart')
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByRole('status')).toHaveText('Saved')
})
