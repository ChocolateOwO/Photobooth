import { defineConfig, mergeConfig } from 'vitest/config'

import viteConfig from './vite.config.ts'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      restoreMocks: true,
      // forks workers time out on this Windows machine; threads are stable
      pool: 'threads',
      // One worker for every file: with isolate=true Vitest spawns a fresh worker per file, which
      // intermittently exceeded its fixed worker start timeout here ("Timeout waiting for worker
      // to respond"). The suites do not share module state.
      maxWorkers: 1,
      fileParallelism: false,
      isolate: false,
      testTimeout: 30_000,
    },
  }),
)
