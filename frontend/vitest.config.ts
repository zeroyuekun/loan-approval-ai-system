/// <reference types="vitest/config" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    exclude: ['e2e/**', 'node_modules/**'],
    coverage: {
      provider: 'v8',
      include: ['src/components/**', 'src/hooks/**', 'src/lib/**'],
      // vitest 4 / @vitest/coverage-v8 4 changed branch/function counting
      // relative to v3 (branches 78.6 → 63.2, functions 78.0 → 74.8 on the
      // same source). Thresholds lowered to the new measurement baseline;
      // actual test coverage didn't regress, only the reporter math.
      thresholds: {
        lines: 65,
        statements: 65,
        functions: 70,
        branches: 60,
      },
    },
  },
})
