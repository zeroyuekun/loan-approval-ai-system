import nextCoreWebVitals from 'eslint-config-next/core-web-vitals'

// Next.js 16 removed `next lint`; ESLint 9 flat config replaces .eslintrc.json.
// eslint-config-next/core-web-vitals is already a flat-config array.
export default [
  {
    ignores: [
      '.next/**',
      'node_modules/**',
      'coverage/**',
      'playwright-report/**',
      'test-results/**',
      'public/**',
      'next-env.d.ts',
    ],
  },
  ...nextCoreWebVitals,
  {
    // eslint-plugin-react-hooks v7 (shipped with eslint-config-next 16) adds
    // React-Compiler-era rules that flag pre-existing patterns. Demote to warn
    // so the upgrade can land; follow-up issue tracks migrating to the new
    // effect/component patterns.
    rules: {
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/static-components': 'warn',
      'react-hooks/incompatible-library': 'warn',
    },
  },
]
