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
      // One worker: parallel jsdom worker start-up exceeded Vitest's fixed 60 s start timeout here.
      maxWorkers: 1,
      fileParallelism: false,
      testTimeout: 30_000,
    },
  }),
)
