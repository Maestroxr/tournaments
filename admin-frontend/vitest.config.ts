import { fileURLToPath } from 'node:url'
import { mergeConfig, defineConfig, configDefaults } from 'vitest/config'
import viteConfig from './vite.config'

export default defineConfig(async () => {
  const viteCfg =
    typeof viteConfig === 'function'
      ? await (viteConfig as unknown as (opts: { mode: string }) => Promise<Record<string, unknown>> | Record<string, unknown>)({ mode: 'test' })
      : viteConfig
  return mergeConfig(viteCfg as Record<string, unknown>, {
    test: {
      environment: 'jsdom',
      exclude: [...configDefaults.exclude, 'e2e/**'],
      root: fileURLToPath(new URL('./', import.meta.url)),
    },
  })
})
