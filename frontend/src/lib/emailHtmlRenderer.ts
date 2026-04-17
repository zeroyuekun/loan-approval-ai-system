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

function extractLoanDetails(body: string): { rows: Array<[string, string]>; start: number; end: number } {
  const lines = body.split('\n')
  let start = -1
  let end = -1
  const rows: Array<[string, string]> = []
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (start === -1) {
      if (line.trim() === 'Loan Details:') {
        start = i
        end = i
      }
      continue
    }
    const m = line.match(LOAN_DETAIL_RE)
    if (m) {
      rows.push([m[2].replace(/:+$/, '').trim(), m[3].trim()])
      end = i
      continue
    }
    if (line.trim() === '') continue
    break
  }
  return { rows, start, end }
}

function renderLoanDetailsCard(rows: Array<[string, string]>): string {
  let rowHtml = ''
  rows.forEach(([label, value], i) => {
    const isLast = i === rows.length - 1
    const border = isLast ? '' : `border-bottom:1px solid ${TOKENS.BORDER};`
    rowHtml += (
      `<tr>` +
      `<td style="padding:8px 0; font-size:14px; color:${TOKENS.MUTED}; ${border}">${label}</td>` +
      `<td style="padding:8px 0; font-size:14px; color:${TOKENS.TEXT}; ` +
      `font-weight:600; text-align:right; ${border}">${value}</td>` +
      `</tr>`
    )
  })
  return (
    `<div style="margin:16px 0;">` +
    `<table role="presentation" style="width:100%; background-color:${TOKENS.CARD_BG}; ` +
    `border-left:4px solid ${TOKENS.SUCCESS}; border-radius:4px;">` +
    `<tr><td style="padding:16px 20px;">` +
    `<div style="font-size:${TOKENS.LABEL_SIZE}; font-weight:600; ` +
    `color:${TOKENS.BRAND_PRIMARY}; text-transform:uppercase; ` +
    `letter-spacing:0.5px; padding-bottom:8px;">Loan Details</div>` +
    `<table role="presentation" style="width:100%;">${rowHtml}</table>` +
    `</td></tr></table>` +
    `</div>`
  )
}

const NUMBERED_STEP_RE = /^\s+(\d+)\.\s+(.+)$/
const HR_LINE_RE = /^[\u2500\u2501\-]{5,}$/

const DEFAULT_APPROVAL_ATTACHMENTS = [
  'Loan Contract.pdf',
  'Key Facts Sheet.pdf',
  'Credit Guide.pdf',
]

function extractNumberedSteps(body: string, sectionLabel: string): { steps: string[]; start: number; end: number } {
  const lines = body.split('\n')
  let start = -1
  let lastNum = -1
  const steps: string[] = []
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (start === -1) {
      if (line.trim() === sectionLabel) start = i
      continue
    }
    const m = line.match(NUMBERED_STEP_RE)
    if (m) {
      steps.push(m[2].trim())
      lastNum = i
      continue
    }
    if (steps.length && line.trim() === '') continue
    if (steps.length && line.trim() !== '') break
  }
  return { steps, start, end: lastNum }
}

function renderNextStepsBlock(steps: string[]): string {
  let rows = ''
  steps.forEach((text, idx) => {
    const i = idx + 1
    rows += (
      `<tr>` +
      `<td style="width:28px; padding:0 0 12px 0; vertical-align:top;">` +
      `<div style="width:24px; height:24px; border-radius:12px; ` +
      `background-color:${TOKENS.BRAND_PRIMARY}; color:#ffffff; ` +
      `font-size:12px; font-weight:600; line-height:24px; text-align:center;">${i}</div>` +
      `</td>` +
      `<td style="padding:0 0 12px 12px; font-size:${TOKENS.BODY_SIZE}; ` +
      `color:${TOKENS.TEXT};">${text}</td>` +
      `</tr>`
    )
  })
  return (
    `<div style="padding:8px 0 16px 0;">` +
    `<div style="font-size:${TOKENS.LABEL_SIZE}; font-weight:600; ` +
    `color:${TOKENS.MUTED}; text-transform:uppercase; letter-spacing:0.5px; ` +
    `padding-bottom:12px;">Next Steps</div>` +
    `<table role="presentation" style="width:100%;">${rows}</table>` +
    `</div>`
  )
}

function renderCta(text: string, href: string, color?: string): string {
  const bg = color ?? TOKENS.BRAND_ACCENT
  return (
    `<div style="padding:8px 0 24px 0; text-align:center;">` +
    `<table role="presentation" cellspacing="0" cellpadding="0" ` +
    `style="margin:0 auto;">` +
    `<tr><td style="background-color:${bg}; border-radius:6px;">` +
    `<a href="${href}" target="_blank" ` +
    `style="display:inline-block; padding:12px 28px; color:#ffffff; ` +
    `font-size:${TOKENS.BODY_SIZE}; font-weight:600; ` +
    `text-decoration:none;">${text}</a>` +
    `</td></tr></table>` +
    `</div>`
  )
}

function renderAttachmentsChips(names: string[]): string {
  if (!names.length) return ''
  const chips = names
    .map(
      (n) =>
        `<td style="padding:6px 12px; background-color:${TOKENS.PAGE_BG}; ` +
        `border:1px solid ${TOKENS.BORDER}; border-radius:4px; ` +
        `font-size:${TOKENS.LABEL_SIZE}; color:#374151;">&#128206; ${n}</td>`
    )
    .join('<td style="width:8px;"></td>')
  return (
    `<div style="padding:8px 0 16px 0;">` +
    `<div style="font-size:${TOKENS.LABEL_SIZE}; font-weight:600; ` +
    `color:${TOKENS.MUTED}; text-transform:uppercase; letter-spacing:0.5px; ` +
    `padding-bottom:8px;">Attachments</div>` +
    `<table role="presentation"><tr>${chips}</tr></table>` +
    `</div>`
  )
}

function splitAtSignature(body: string): { preSig: string; sigLines: string[]; postSig: string } {
  const lines = body.split('\n')
  const sigStart = lines.findIndex((ln) => CLOSINGS.includes(ln.trim()))
  if (sigStart === -1) return { preSig: body, sigLines: [], postSig: '' }
  let sigEnd = lines.length
  for (let j = sigStart + 1; j < lines.length; j++) {
    if (HR_LINE_RE.test(lines[j].trim())) {
      sigEnd = j
      break
    }
  }
  return {
    preSig: lines.slice(0, sigStart).join('\n'),
    sigLines: lines.slice(sigStart, sigEnd),
    postSig: lines.slice(sigEnd).join('\n'),
  }
}

function renderSignatureBlock(sigLines: string[]): string {
  if (!sigLines.length) return ''
  const closing = sigLines[0].trim()
  const nonBlank = sigLines.slice(1).map((ln) => ln.trim()).filter(Boolean)
  const name = nonBlank[0] ?? ''
  const title = nonBlank[1] ?? ''
  const company = nonBlank[2] ?? ''
  const contactPrefixes = ['ABN ', 'Ph:', 'Phone:', 'Email:', 'Website:']
  const contact = nonBlank.slice(3).filter((ln) => contactPrefixes.some((p) => ln.startsWith(p)))
  const contactHtml = contact
    .map(
      (ln) =>
        `<div style="font-size:${TOKENS.FINE_SIZE}; color:${TOKENS.FINE};">${ln}</div>`
    )
    .join('')
  return (
    `<div style="padding:24px 0 0 0; margin-top:16px; ` +
    `border-top:1px solid ${TOKENS.BORDER};">` +
    `<div style="font-size:${TOKENS.BODY_SIZE}; color:${TOKENS.TEXT}; ` +
    `padding-bottom:8px;">${closing}</div>` +
    `<div style="font-size:${TOKENS.BODY_SIZE}; color:${TOKENS.TEXT}; ` +
    `font-weight:600;">${name}</div>` +
    `<div style="font-size:${TOKENS.LABEL_SIZE}; color:${TOKENS.MUTED};">${title}</div>` +
    `<div style="font-size:${TOKENS.LABEL_SIZE}; color:${TOKENS.MUTED}; ` +
    `padding-bottom:8px;">${company}</div>` +
    `${contactHtml}` +
    `</div>`
  )
}

function renderApprovalBody(plainBody: string): string {
  const { rows: ldRows, start: ldStart, end: ldEnd } = extractLoanDetails(plainBody)
  const { steps: nsSteps, start: nsStart, end: nsEnd } = extractNumberedSteps(plainBody, 'Next Steps:')
  const { preSig, sigLines, postSig } = splitAtSignature(plainBody)
  const preSigEndIdx = preSig ? preSig.split('\n').length : 0

  const lines = plainBody.split('\n')
  const parts: string[] = []
  let buffer: string[] = []

  const flush = () => {
    if (buffer.length) {
      parts.push(renderLegacyBody(buffer.join('\n')))
      buffer = []
    }
  }

  let i = 0
  while (i < preSigEndIdx) {
    if (ldRows.length && i === ldStart) {
      flush()
      parts.push(renderLoanDetailsCard(ldRows))
      i = ldEnd + 1
      continue
    }
    if (nsSteps.length && i === nsStart) {
      flush()
      parts.push(renderNextStepsBlock(nsSteps))
      parts.push(renderCta('Review &amp; Sign Documents', 'https://portal.aussieloanai.com.au/sign'))
      i = nsEnd + 1
      continue
    }
    buffer.push(lines[i])
    i++
  }
  flush()

  if (nsSteps.length) {
    parts.push(renderAttachmentsChips(DEFAULT_APPROVAL_ATTACHMENTS))
  }
  parts.push(renderSignatureBlock(sigLines))
  if (postSig.trim()) {
    parts.push(renderLegacyBody(postSig))
  }
  return parts.join('')
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
  const bodyHtml = emailType === 'approval' ? renderApprovalBody(plainBody) : renderLegacyBody(plainBody)
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
    `color:${TOKENS.TEXT};">${bodyHtml}</td></tr>` +
    `${renderFooterShell()}` +
    `</table>` +
    `</td></tr>` +
    `</table>`
  )
}
