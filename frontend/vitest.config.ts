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
      // One worker for every file: spawning a worker per file intermittently exceeded Vitest's
      // fixed worker start timeout on this machine ("Timeout waiting for worker to respond").
      maxWorkers: 1,
      fileParallelism: false,
      poolOptions: { threads: { singleThread: true } },
      testTimeout: 30_000,
    },
  }),
)
