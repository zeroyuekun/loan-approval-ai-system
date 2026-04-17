/**
 * TypeScript mirror of backend/apps/email_engine/services/html_renderer.py.
 * CI parity test diffs Python vs TS snapshots — any drift fails the build.
 *
 * See: docs/superpowers/specs/2026-04-17-email-redesign-design.md
 */

export type EmailType = 'approval' | 'denial' | 'marketing'

export const TOKENS = {
  BRAND_PRIMARY: '#1e40af',
  BRAND_ACCENT: '#3b82f6',
  SUCCESS: '#16a34a',
  CAUTION: '#d97706',
  MARKETING: '#7c3aed',
  TEXT: '#111827',
  MUTED: '#6b7280',
  FINE: '#9ca3af',
  CARD_BG: '#f8fafc',
  BORDER: '#e5e7eb',
  PAGE_BG: '#f3f4f6',
  FONT_STACK: "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif",
  BODY_SIZE: '15px',
  HEAD_SIZE: '22px',
  LABEL_SIZE: '13px',
  FINE_SIZE: '12px',
  LINE_HEIGHT: '1.6',
  MAX_WIDTH: '600px',
} as const

const SECTION_LABELS = [
  'Loan Details:',
  'Next Steps:',
  'Required Documentation:',
  'Before You Sign:',
  "We're Here For You:",
  'What You Can Do:',
  "We'd Still Like to Help:",
  'Attachments:',
  'Conditions of Approval:',
  'This decision was based on a thorough review of your financial profile, specifically:',
]
const CLOSINGS = ['Kind regards,', 'Warm regards,']
const OPTION_RE = /^Option\s+\d+[\s:.\-\u2013\u2014]/
const LOAN_DETAIL_RE = /^(\s{2,})(\S[^:]+:)\s+(.+)$/
const HR_RE = /^[\u2500\u2501\-]{5,}$/
const BULLET_RE = /^[\u2022•]\s*(.+)$/
const NUM_RE = /^\s+(\d+)\.\s+(.+)$/
const APPROVAL_LOAN_TYPE_RE = /application for an? ([A-Z][A-Za-z]+ Loan)/

type HeroEntry = { icon: string; color: string; defaultHeadline: string }
const HERO_CONFIG: Record<EmailType, HeroEntry> = {
  approval: { icon: '&#10003;', color: TOKENS.SUCCESS, defaultHeadline: 'Your Loan Is Approved' },
  denial: { icon: '&#9432;', color: TOKENS.CAUTION, defaultHeadline: 'Update on Your Application' },
  marketing: { icon: '&#10022;', color: TOKENS.MARKETING, defaultHeadline: 'A Few Options for You' },
}

function extractApplicantName(body: string): string {
  const lines = body.split('\n').slice(0, 5)
  for (const line of lines) {
    const s = line.trim()
    if (s.startsWith('Dear ')) {
      const rest = s.substring(5).replace(/,+$/, '').trim()
      if (!rest) return 'there'
      return rest.split(/\s+/)[0]
    }
  }
  return 'there'
}

function extractApprovalLoanType(body: string): string {
  const m = body.match(APPROVAL_LOAN_TYPE_RE)
  return m ? m[1] : 'Loan'
}

function renderHero(emailType: EmailType, body: string): string {
  const cfg = HERO_CONFIG[emailType]
  const name = extractApplicantName(body)
  let headline: string
  let subtitle: string
  if (emailType === 'approval') {
    const loanType = extractApprovalLoanType(body)
    headline = `Your ${loanType} Is Approved`
    subtitle = `Congratulations, ${name}!`
  } else if (emailType === 'denial') {
    headline = cfg.defaultHeadline
    subtitle = `${name}, we've reviewed your application`
  } else {
    headline = cfg.defaultHeadline
    subtitle = 'A few options tailored to you'
  }
  return (
    `<tr><td style="padding:32px 24px 16px 24px; ` +
    `font-family:${TOKENS.FONT_STACK};">` +
    `<div style="width:48px; height:48px; border-radius:24px; ` +
    `background-color:${cfg.color}; text-align:center; ` +
    `line-height:48px; color:#ffffff; font-size:24px; ` +
    `font-weight:600;">${cfg.icon}</div>` +
    `<h1 style="font-size:${TOKENS.HEAD_SIZE}; line-height:28px; ` +
    `color:${TOKENS.TEXT}; margin:12px 0 4px 0; font-weight:600;">` +
    `${headline}</h1>` +
    `<div style="font-size:${TOKENS.LABEL_SIZE}; ` +
    `color:${TOKENS.MUTED};">${subtitle}</div>` +
    `</td></tr>`
  )
}

function renderLegacyBody(body: string): string {
  const lines = body.split('\n')
  const parts: string[] = []
  let detailRows: string[] = []
  const tdLabel = 'style="padding:4px 8px 4px 0;color:#888;border-bottom:1px solid #f0f0f0;"'
  const tdValue = 'style="padding:4px 0 4px 8px;text-align:right;border-bottom:1px solid #f0f0f0;"'

  const flushRows = () => {
    if (detailRows.length) {
      parts.push(`<table style="width:100%;border-collapse:collapse;margin:8px 0;">${detailRows.join('')}</table>`)
      detailRows = []
    }
  }

  for (const line of lines) {
    const stripped = line.trim()
    const isSection = SECTION_LABELS.includes(stripped)
    const isOption = OPTION_RE.test(stripped)
    const isDear = stripped.startsWith('Dear ')
    const isClosing = CLOSINGS.includes(stripped)

    if (isSection || isOption) {
      flushRows()
      parts.push(`<p style="margin:20px 0 4px 0;"><strong>${stripped}</strong></p>`)
      continue
    }
    if (isDear) {
      flushRows()
      parts.push(`<p style="margin:0 0 4px 0;"><strong>${stripped}</strong></p>`)
      continue
    }
    if (isClosing) {
      flushRows()
      parts.push(`<p style="margin:20px 0 4px 0;"><strong>${stripped}</strong></p>`)
      continue
    }

    const bulletMatch = stripped.match(BULLET_RE)
    if (bulletMatch) {
      flushRows()
      parts.push(`<p style="margin:2px 0 2px 16px;">\u2022&nbsp;&nbsp;${bulletMatch[1]}</p>`)
      continue
    }

    const numMatch = line.match(NUM_RE)
    if (numMatch) {
      flushRows()
      parts.push(`<p style="margin:2px 0 2px 16px;">${numMatch[1]}. ${numMatch[2]}</p>`)
      continue
    }

    const detailMatch = line.match(LOAN_DETAIL_RE)
    if (detailMatch) {
      const label = detailMatch[2]
      const value = detailMatch[3]
      if (label.length < 35 && value.length < 50) {
        detailRows.push(`<tr><td ${tdLabel}>${label}</td><td ${tdValue}>${value}</td></tr>`)
        continue
      }
    }

    flushRows()

    if (HR_RE.test(stripped)) {
      parts.push('<hr style="border:none;border-top:1px solid #ddd;margin:16px 0;">')
      continue
    }

    if (
      stripped.startsWith('ABN ') ||
      stripped.startsWith('Ph:') ||
      stripped.startsWith('Phone:') ||
      stripped.startsWith('Email:') ||
      stripped.startsWith('Website:')
    ) {
      parts.push(`<p style="margin:0;font-size:12px;color:#888;">${stripped}</p>`)
      continue
    }

    if (stripped === '') {
      parts.push('<div style="height:12px;"></div>')
      continue
    }

    const margin = stripped.endsWith('.') ? '16px' : '4px'
    const topMargin = stripped.startsWith('Congratulations') ? '16px' : '0'
    parts.push(`<p style="margin:${topMargin} 0 ${margin} 0;">${stripped}</p>`)
  }

  flushRows()
  return parts.join('\n')
}

function renderHeader(): string {
  return (
    `<tr><td style="background-color:${TOKENS.BRAND_PRIMARY}; ` +
    `padding:16px 24px; border-radius:8px 8px 0 0;">` +
    `<span style="color:#ffffff; font-size:16px; font-weight:600; ` +
    `letter-spacing:0.3px;">AussieLoanAI</span>` +
    `<span style="color:#bfdbfe; font-size:12px; margin-left:8px;">` +
    `Australian Credit Licence No. 012345</span>` +
    `</td></tr>`
  )
}

function renderFooterShell(): string {
  return (
    `<tr><td style="padding:24px; background-color:${TOKENS.CARD_BG}; ` +
    `border-radius:0 0 8px 8px; font-size:${TOKENS.FINE_SIZE}; ` +
    `color:${TOKENS.FINE};">&nbsp;</td></tr>`
  )
}

export function renderEmailHtml(plainBody: string, emailType: EmailType): string {
  const bodyHtml = renderLegacyBody(plainBody)
  return (
    `<table role="presentation" cellpadding="0" cellspacing="0" border="0" ` +
    `style="width:100%; background-color:${TOKENS.PAGE_BG}; margin:0; padding:0;">` +
    `<tr><td style="padding:32px 16px;">` +
    `<table role="presentation" cellpadding="0" cellspacing="0" border="0" ` +
    `style="width:100%; max-width:${TOKENS.MAX_WIDTH}; margin:0 auto; ` +
    `background-color:#ffffff; border-radius:8px; ` +
    `box-shadow:0 1px 3px rgba(0,0,0,0.06);">` +
    `${renderHeader()}` +
    `${renderHero(emailType, plainBody)}` +
    `<tr><td style="padding:0 24px 24px 24px; font-family:${TOKENS.FONT_STACK}; ` +
    `font-size:${TOKENS.BODY_SIZE}; line-height:${TOKENS.LINE_HEIGHT}; ` +
    `color:${TOKENS.TEXT};">` +
    `${bodyHtml}` +
    `</td></tr>` +
    `${renderFooterShell()}` +
    `</table>` +
    `</td></tr>` +
    `</table>`
  )
}
