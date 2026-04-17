import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

describe('EmailPreview uses shared renderer', () => {
  it('does not define local plainTextToHtml', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '../../components/emails/EmailPreview.tsx'),
      'utf-8',
    )
    expect(src).not.toContain('function plainTextToHtml')
  })

  it('imports renderEmailHtml from shared module', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '../../components/emails/EmailPreview.tsx'),
      'utf-8',
    )
    expect(src).toContain("import { renderEmailHtml } from '@/lib/emailHtmlRenderer'")
  })
})
