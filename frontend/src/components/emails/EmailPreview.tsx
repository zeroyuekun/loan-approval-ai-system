'use client'

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { GeneratedEmail } from '@/types'
import { GuardrailLogDisplay } from './GuardrailLogDisplay'
import { CheckCircle, XCircle, Clock } from 'lucide-react'

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

// Inline patterns for key figures: interest rates and percentage figures
const INLINE_BOLD_PATTERN = /(\d+\.\d+%\s*p\.a\.|\d+\.\d+%)/

function renderLineWithInlineBold(line: string, key: number) {
  const parts = line.split(INLINE_BOLD_PATTERN)
  if (parts.length === 1) {
    return <span key={key}>{line}{'\n'}</span>
  }
  return (
    <span key={key}>
      {parts.map((part, j) =>
        INLINE_BOLD_PATTERN.test(part)
          ? <strong key={j}>{part}</strong>
          : part
      )}
      {'\n'}
    </span>
  )
}

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
        if (isSection || isDear || isSubject || isOption) {
          return (
            <span key={i}>
              <strong>{line}</strong>{'\n'}
            </span>
          )
        }


        // Bullet-point lines: render plain (no bold)
        if (trimmed.startsWith('•') || trimmed.startsWith('\u2022')) {
          return <span key={i}>{line}{'\n'}</span>
        }

        // Body text: inline-bold key figures (rates, percentages)
        return renderLineWithInlineBold(line, i)
      })}
    </>
  )
}

interface EmailPreviewProps {
  email: GeneratedEmail
}

export function EmailPreview({ email }: EmailPreviewProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Generated Email</CardTitle>
          <div className="flex items-center gap-2">
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
        <CardDescription className="flex items-center gap-4">
          <span>Attempt #{email.attempt_number}</span>
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {email.generation_time_ms}ms
          </span>
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
