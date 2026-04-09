'use client'

import DOMPurify from 'dompurify'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { GeneratedEmail } from '@/types'
import { GuardrailLogDisplay } from './GuardrailLogDisplay'
import { CheckCircle, XCircle, Clock, Mail } from 'lucide-react'

export function HtmlEmailBody({ html }: { html: string }) {
  const sanitized = DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['div', 'p', 'strong', 'em', 'br', 'hr', 'table', 'tr', 'td', 'th', 'span', 'b', 'i', 'u', 'a', 'ul', 'ol', 'li', 'h1', 'h2', 'h3'],
    ALLOWED_ATTR: ['style', 'href'],
  })

  return (
    <div
      className="email-html-preview [&_p]:my-2 [&_table]:my-3 [&_hr]:my-4 [&_hr]:border-gray-200"
      dangerouslySetInnerHTML={{ __html: sanitized }}
    />
  )
}

/** Fallback: convert plain text to basic HTML paragraphs when no html_body exists */
function plainTextToHtml(body: string): string {
  const escaped = body.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return '<div style="font-family: Arial, Helvetica, sans-serif; font-size: 14px; line-height: 1.6; color: #333;">'
    + escaped.split('\n\n').map(block =>
        `<p style="margin: 0 0 16px 0;">${block.replace(/\n/g, '<br>')}</p>`
      ).join('')
    + '</div>'
}

interface EmailPreviewProps {
  email: GeneratedEmail
}

export function EmailPreview({ email }: EmailPreviewProps) {
  const htmlContent = email.html_body || plainTextToHtml(email.body)

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Mail className="h-4 w-4" />
            Generated Email
          </CardTitle>
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
        {/* Gmail-style email preview */}
        <div className="rounded-lg border bg-white shadow-soft overflow-hidden">
          {/* Email header bar */}
          <div className="border-b bg-gray-50/80 px-6 py-3">
            <p className="text-sm font-semibold text-foreground">{email.subject}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              From: AussieLoanAI &lt;decisions@aussieloanai.com.au&gt;
            </p>
          </div>
          {/* Email body */}
          <div className="px-6 py-5 text-sm leading-relaxed">
            <HtmlEmailBody html={htmlContent} />
          </div>
        </div>

        {email.guardrail_checks && email.guardrail_checks.length > 0 && (
          <GuardrailLogDisplay checks={email.guardrail_checks} />
        )}
      </CardContent>
    </Card>
  )
}
