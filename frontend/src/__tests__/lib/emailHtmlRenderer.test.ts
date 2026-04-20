import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import {
  TOKENS,
  renderEmailHtml,
  escapeHtml,
  safeUrl,
  SAFE_URL_FALLBACK,
  type EmailType,
} from '@/lib/emailHtmlRenderer'

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
    'denial_06_live_shape',
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

// ---------------------------------------------------------------------------
// HTML escape parity with backend/apps/email_engine/services/html_renderer.py
// ---------------------------------------------------------------------------

describe('escapeHtml', () => {
  it('matches the Python _e() five-char contract', () => {
    expect(escapeHtml('&')).toBe('&amp;')
    expect(escapeHtml('<')).toBe('&lt;')
    expect(escapeHtml('>')).toBe('&gt;')
    expect(escapeHtml('"')).toBe('&quot;')
    expect(escapeHtml("'")).toBe('&#x27;')
    expect(escapeHtml('plain text')).toBe('plain text')
    expect(escapeHtml('a&b<c>d"e\'f')).toBe('a&amp;b&lt;c&gt;d&quot;e&#x27;f')
  })

  it('does not double-escape already-escaped entities', () => {
    // After a single pass, the raw `&` in `&amp;` becomes `&amp;` again → `&amp;amp;`.
    // This is expected: we always escape once. Input must arrive unescaped.
    expect(escapeHtml('&amp;')).toBe('&amp;amp;')
  })
})

const XSS_APPROVAL_BODY =
  'Dear <script>alert("x\'s")</script>,\n\n' +
  'Congratulations! Your Personal Loan has been approved.\n\n' +
  'Loan Details:\n' +
  '- Loan Type: <img src=x onerror=alert(1)>\n' +
  '- Amount: $15,000\n' +
  '- Term: 3 years\n' +
  '- Interest Rate: 12.5% p.a.\n\n' +
  'We\'re Here For You:\n' +
  'Reach us at "support@aussieloanai.com".\n\n' +
  'Kind regards,\n' +
  'The AussieLoanAI "Team"\n'

const XSS_DENIAL_BODY =
  'Dear <b>attacker</b>,\n\n' +
  'Unfortunately we are unable to approve your application at this time.\n\n' +
  'Factors:\n' +
  'Serviceability: debt-to-income exceeds <script>alert(1)</script> policy\n' +
  "Credit: score below our O'Brien benchmark\n\n" +
  'What you can do:\n' +
  '- Visit "https://example.com/help" for guidance\n' +
  '- Reapply after 3 months\n'

describe('renderEmailHtml escapes untrusted markup', () => {
  it.each<[string, EmailType]>([
    [XSS_APPROVAL_BODY, 'approval'],
    [XSS_DENIAL_BODY, 'denial'],
  ])('escapes injected <script> / <img> / quotes in %s body', (body, emailType) => {
    const out = renderEmailHtml(body, emailType)
    expect(out).not.toContain('<script>')
    expect(out).not.toContain('<img src=x')
    expect(out).toContain('&lt;script&gt;')
    expect(out).toContain('&quot;')
    expect(out).toContain('&#x27;')
  })

  it('escapes `&` without double-escaping downstream', () => {
    const body =
      'Dear Jane & Co,\n\n' +
      'Your loan is approved.\n\n' +
      'Loan Details:\n' +
      '- Loan Type: Personal & Household\n' +
      '- Amount: $10,000\n\n' +
      'Regards,\nTeam\n'
    const out = renderEmailHtml(body, 'approval')
    expect(out).toContain('Jane &amp; Co')
    expect(out).toContain('Personal &amp; Household')
    expect(out).not.toContain('Jane & Co')
  })
})

describe('safeUrl', () => {
  it('accepts http, https, mailto, tel schemes', () => {
    expect(safeUrl('https://example.com/path')).toBe('https://example.com/path')
    expect(safeUrl('http://example.com')).toBe('http://example.com')
    expect(safeUrl('mailto:user@example.com')).toBe('mailto:user@example.com')
    expect(safeUrl('tel:1300000000')).toBe('tel:1300000000')
  })

  it('accepts schemes case-insensitively', () => {
    expect(safeUrl('HTTPS://example.com')).toBe('HTTPS://example.com')
    expect(safeUrl('HttP://example.com')).toBe('HttP://example.com')
  })

  it('strips surrounding whitespace', () => {
    expect(safeUrl('  https://example.com  ')).toBe('https://example.com')
  })

  it('rejects the javascript: scheme in any casing', () => {
    expect(safeUrl('javascript:alert(1)')).toBe(SAFE_URL_FALLBACK)
    expect(safeUrl('JaVaScRiPt:alert(1)')).toBe(SAFE_URL_FALLBACK)
    expect(safeUrl(' javascript:alert(1)')).toBe(SAFE_URL_FALLBACK)
  })

  it('rejects other dangerous schemes', () => {
    expect(safeUrl('data:text/html,<script>alert(1)</script>')).toBe(SAFE_URL_FALLBACK)
    expect(safeUrl('vbscript:msgbox(1)')).toBe(SAFE_URL_FALLBACK)
    expect(safeUrl('file:///etc/passwd')).toBe(SAFE_URL_FALLBACK)
  })

  it('rejects schemeless or garbage input', () => {
    expect(safeUrl('')).toBe(SAFE_URL_FALLBACK)
    expect(safeUrl('not a url')).toBe(SAFE_URL_FALLBACK)
    expect(safeUrl('//example.com/path')).toBe(SAFE_URL_FALLBACK)
  })
})

describe('marketing footer URL sanitisation', () => {
  it('strips javascript: URLs injected via the LLM-parsed unsubscribe line', () => {
    const body =
      'Dear Customer,\n\n' +
      'Special term deposit offer.\n\n' +
      'Sarah\n\n' +
      'ABN 00 000 000 000\n' +
      "Unsubscribe: javascript:alert('xss')"
    const out = renderEmailHtml(body, 'marketing')
    // The dangerous scheme must never appear inside an href — it's fine if it
    // remains in body text (it's escaped and harmless there).
    const hrefs = Array.from(out.matchAll(/href\s*=\s*"([^"]*)"/g)).map((m) => m[1])
    for (const href of hrefs) {
      expect(href.toLowerCase().startsWith('javascript:')).toBe(false)
    }
    expect(out).toContain('href="https://aussieloanai.com.au/unsubscribe"')
  })

  it('preserves a legitimate unsubscribe URL', () => {
    const body =
      'Dear Customer,\n\n' +
      'Special offer.\n\n' +
      'Sarah\n\n' +
      'ABN 00 000 000 000\n' +
      'Unsubscribe: https://aussieloanai.com.au/unsubscribe?u=abc123'
    const out = renderEmailHtml(body, 'marketing')
    expect(out).toContain('https://aussieloanai.com.au/unsubscribe?u=abc123')
  })
})
