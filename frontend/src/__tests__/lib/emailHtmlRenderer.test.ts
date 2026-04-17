import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { TOKENS, renderEmailHtml, type EmailType } from '@/lib/emailHtmlRenderer'

describe('TOKENS', () => {
  it('has required keys', () => {
    const required = [
      'BRAND_PRIMARY', 'BRAND_ACCENT', 'SUCCESS', 'CAUTION', 'MARKETING',
      'TEXT', 'MUTED', 'FINE', 'CARD_BG', 'BORDER', 'PAGE_BG',
      'FONT_STACK', 'BODY_SIZE', 'HEAD_SIZE', 'LABEL_SIZE', 'FINE_SIZE',
      'LINE_HEIGHT', 'MAX_WIDTH',
    ]
    for (const key of required) {
      expect(TOKENS).toHaveProperty(key)
    }
  })

  it('brand colors match spec', () => {
    expect(TOKENS.BRAND_PRIMARY).toBe('#1e40af')
    expect(TOKENS.BRAND_ACCENT).toBe('#3b82f6')
    expect(TOKENS.SUCCESS).toBe('#16a34a')
    expect(TOKENS.CAUTION).toBe('#d97706')
    expect(TOKENS.MARKETING).toBe('#7c3aed')
  })
})

describe('renderEmailHtml', () => {
  it('returns a string', () => {
    const result = renderEmailHtml('Dear John,\n\nHello.', 'approval')
    expect(typeof result).toBe('string')
  })

  it('includes the body text', () => {
    const result = renderEmailHtml('Dear John,\n\nHello.', 'approval')
    expect(result).toContain('Dear John,')
    expect(result).toContain('Hello.')
  })

  it('includes brand header', () => {
    const result = renderEmailHtml('Dear John,', 'approval')
    expect(result).toContain('AussieLoanAI')
    expect(result).toContain(TOKENS.BRAND_PRIMARY)
  })

  it('uses 600px max-width', () => {
    const result = renderEmailHtml('Dear John,', 'approval')
    expect(result).toContain('max-width:600px')
  })
})

const FIXTURE_DIR = path.resolve(__dirname, '../fixtures/email_bodies')
const SNAPSHOT_DIR = path.resolve(__dirname, '../fixtures/email_snapshots')

function typeForFixture(name: string): EmailType {
  if (name.startsWith('approval')) return 'approval'
  if (name.startsWith('denial')) return 'denial'
  return 'marketing'
}

describe('snapshot parity with Python renderer', () => {
  const stems = [
    'approval_01_personal',
    'approval_02_home_loan',
    'approval_03_with_cosigner',
    'approval_04_conditional',
    'approval_05_auto_loan',
    'denial_01_serviceability',
    'denial_02_credit_score',
    'denial_03_employment',
    'denial_04_multiple_factors',
    'denial_05_policy',
    'marketing_01_three_options',
    'marketing_02_two_options',
    'marketing_03_single_option',
    'marketing_04_term_deposit',
    'marketing_05_bonus_rate',
  ]
  for (const stem of stems) {
    it(`${stem} matches Python snapshot byte-for-byte`, () => {
      const body = fs.readFileSync(path.join(FIXTURE_DIR, `${stem}.txt`), 'utf-8')
      const actual = renderEmailHtml(body, typeForFixture(stem))
      const expected = fs.readFileSync(path.join(SNAPSHOT_DIR, `${stem}.html`), 'utf-8')
      expect(actual).toBe(expected)
    })
  }
})
