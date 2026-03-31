'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { GeneratedEmail } from '@/types'
import { GuardrailLogDisplay } from './GuardrailLogDisplay'
import { emailApi } from '@/lib/api'
import { CheckCircle, XCircle, Clock, Send } from 'lucide-react'

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

const CLOSINGS = [
  'Kind regards,',
  'Warm regards,',
]

const OPTION_PATTERN = /^Option\s+\d+[\s:.\-–—]/

// Loan details line pattern: "  Label:  Value" with leading whitespace
const LOAN_DETAIL_LINE = /^(\s{2,})(\S[^:]+:)\s+(.+)$/

export function FormattedEmailBody({ body }: { body: string }) {
  const lines = body.split('\n')

  return (
    <>
      {lines.map((line, i) => {
        const trimmed = line.trim()
        const isSection = SECTION_LABELS.includes(trimmed)
        const isDear = trimmed.startsWith('Dear ')
        const isSignName = trimmed === 'Sarah Mitchell'
        const isSignTitle = trimmed === 'Senior Lending Officer'
        const isSubject = trimmed.startsWith('Subject:')
        const isOption = OPTION_PATTERN.test(trimmed)
        const isClosing = CLOSINGS.includes(trimmed)

        // Full-line bold: section headers, greeting, options
        // Section headers get top margin to breathe from previous paragraph
        if (isSection || isDear || isSubject || isOption) {
          const needsTopSpace = isSection || isOption
          return (
            <span key={i} className={needsTopSpace ? 'block mt-5 mb-1' : 'block mb-1'}>
              <strong>{line}</strong>
            </span>
          )
        }


        // Bullet-point lines: render as clean list items
        const bulletMatch = trimmed.match(/^[•\u2022]\s*(.+)$/)
        if (bulletMatch) {
          // Only format as key:value if the label part is short (e.g. "Amount", "Rate", "Term")
          const colonIdx = bulletMatch[1].indexOf(':')
          if (colonIdx > 0 && colonIdx < 30) {
            const label = bulletMatch[1].substring(0, colonIdx)
            const value = bulletMatch[1].substring(colonIdx + 1).trim()
            if (value) {
              return (
                <span key={i} className="flex justify-between py-0.5 pl-4 border-b border-gray-100">
                  <span className="text-muted-foreground">{label}:</span>
                  <span>{value}</span>
                </span>
              )
            }
          }
          return (
            <span key={i} className="block pl-4 py-0.5">
              <span className="text-muted-foreground mr-2">•</span>{bulletMatch[1]}
            </span>
          )
        }

        // Numbered list items (e.g. "  1. Document name.pdf") — render as clean list
        const numberedMatch = trimmed.match(/^(\d+)\.\s+(.+)$/)
        if (/^\s+\d+\.\s/.test(line) && numberedMatch) {
          return (
            <span key={i} className="flex items-baseline gap-3 py-0.5">
              <span className="text-muted-foreground text-xs w-4 text-right flex-shrink-0">{numberedMatch[1]}.</span>
              <span>{numberedMatch[2]}</span>
            </span>
          )
        }

        // Loan detail lines (e.g. "  Loan Amount:   $35,000.00") — render as clean key-value
        // Only match when value looks like data: starts with $, digit, or % — never sentences
        const detailMatch = line.match(LOAN_DETAIL_LINE)
        if (detailMatch) {
          const [, , label, value] = detailMatch
          if (label.length < 35 && /^[\$\d]/.test(value.trim())) {
            return (
              <span key={i} className="flex justify-between py-0.5 border-b border-gray-100 last:border-0">
                <span className="text-muted-foreground">{label}</span>
                <span>{value}</span>
              </span>
            )
          }
        }

        // Closing line (e.g. "Kind regards,") — add top space
        if (isClosing) {
          return (
            <span key={i} className="block mt-5">
              <strong>{line}</strong>
            </span>
          )
        }

        // Horizontal rule (───────)
        if (/^[─━─\-]{5,}$/.test(trimmed)) {
          return <hr key={i} className="my-4 border-gray-200" />
        }

        // Signature details (ABN, Ph/Phone, Email, Website lines)
        if (trimmed.startsWith('ABN ') || trimmed.startsWith('Ph:') || trimmed.startsWith('Phone:') || trimmed.startsWith('Email:') || trimmed.startsWith('Website:')) {
          return <span key={i} className="block text-xs text-muted-foreground">{trimmed}</span>
        }

        // Company name and title lines in signature block
        if (trimmed === 'AussieLoanAI Pty Ltd' || trimmed === 'Senior Lending Officer' || trimmed === 'Sarah Mitchell') {
          return <span key={i} className="block">{trimmed}</span>
        }

        // Empty lines: render as paragraph break
        if (trimmed === '') {
          return <span key={i} className="block h-3" />
        }

        // Body text: each line ending with a period/sentence is its own paragraph
        const isSentence = trimmed.endsWith('.') || trimmed.endsWith('.')
        const needsTopSpace = trimmed.startsWith('Congratulations')
        return <span key={i} className={`block ${needsTopSpace ? 'mt-4' : ''} ${isSentence ? 'mb-4' : 'mb-1'}`}>{line}</span>
      })}
    </>
  )
}

interface EmailPreviewProps {
  email: GeneratedEmail
}

export function EmailPreview({ email }: EmailPreviewProps) {
  const [sending, setSending] = useState(false)
  const [sendResult, setSendResult] = useState<{ sent: boolean; message: string } | null>(null)

  const handleSendEmail = async () => {
    setSending(true)
    setSendResult(null)
    try {
      const { data } = await emailApi.sendLatest(email.application_id)
      setSendResult({ sent: true, message: `Sent to ${data.recipient}` })
    } catch (error: any) {
      const message = error?.response?.data?.error || error?.message || 'Failed to send'
      setSendResult({ sent: false, message })
    } finally {
      setSending(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Generated Email</CardTitle>
          <div className="flex items-center gap-2">
            {email.passed_guardrails && (
              <Button
                size="sm"
                variant="outline"
                onClick={handleSendEmail}
                disabled={sending}
              >
                <Send className="mr-1 h-3 w-3" />
                {sending ? 'Sending...' : 'Send Email'}
              </Button>
            )}
            {email.passed_guardrails ? (
              <Badge className="bg-green-100 text-green-800" variant="outline">
                <CheckCircle className="mr-1 h-3 w-3" />
                Passed Guardrails
              </Badge>
            ) : (
              <Badge className="bg-red-100 text-red-800" variant="outline">
                <XCircle className="mr-1 h-3 w-3" />
                Failed Guardrails
              </Badge>
            )}
          </div>
        </div>
        <CardDescription className="flex flex-col gap-1">
          <span className="flex items-center gap-4">
            <span>Attempt #{email.attempt_number}</span>
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {email.generation_time_ms}ms
            </span>
          </span>
          {sendResult && (
            <span className={sendResult.sent ? 'text-green-600' : 'text-red-600'}>
              {sendResult.message}
            </span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-lg border bg-white p-6 shadow-soft">
          <div className="mb-4">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Subject</span>
            <p className="mt-1 text-base font-semibold">{email.subject}</p>
          </div>
          <hr className="mb-5" />
          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Body</span>
            <div className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">
              <FormattedEmailBody body={email.body} />
            </div>
          </div>
        </div>

        {email.guardrail_checks && email.guardrail_checks.length > 0 && (
          <GuardrailLogDisplay checks={email.guardrail_checks} />
        )}
      </CardContent>
    </Card>
  )
}
