import { test as base } from '@playwright/test'

export * from '@playwright/test'

/**
 * Every spec's `test`. The real booth asks for the whole screen on a guest's touch; a window that
 * really went fullscreen could no longer be resized by the specs that measure screen sizes. So a
 * request is counted (`window.pbFullscreenAsked`) instead of honoured, and fullscreen itself is
 * checked by hand on the booth machine.
 */
export const test = base.extend<{ windowed: void }>({
  windowed: [
    async ({ context }, use) => {
      await context.addInitScript(() => {
        const counted = window as unknown as { pbFullscreenAsked: number }
        counted.pbFullscreenAsked = 0
        Element.prototype.requestFullscreen = function () {
          counted.pbFullscreenAsked += 1
          return Promise.resolve()
        }
      })
      await use()
    },
    { auto: true },
  ],
})
