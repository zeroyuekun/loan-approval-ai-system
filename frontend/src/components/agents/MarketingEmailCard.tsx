'use client'

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { MarketingEmail } from '@/types'
import { Mail, ShieldCheck, ShieldAlert, Clock, RefreshCw } from 'lucide-react'
import { GuardrailLogDisplay } from '@/components/emails/GuardrailLogDisplay'
import { HtmlEmailBody } from '@/components/emails/EmailPreview'

/** Fallback: convert plain text to basic HTML paragraphs when no html_body exists */
function plainTextToHtml(body: string): string {
  const escaped = body.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return '<div style="font-family: Arial, Helvetica, sans-serif; font-size: 14px; line-height: 1.6; color: #333;">'
    + escaped.split('\n\n').map(block =>
        `<p style="margin: 0 0 16px 0;">${block.replace(/\n/g, '<br>')}</p>`
      ).join('')
    + '</div>'
}

interface MarketingEmailCardProps {
  email: MarketingEmail
}

export function MarketingEmailCard({ email }: MarketingEmailCardProps) {
  const htmlContent = email.html_body || plainTextToHtml(email.body)

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Mail className="h-4 w-4 text-purple-600" />
            Marketing Email
            {email.passed_guardrails ? (
              <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200 ml-2">
                <ShieldCheck className="h-3 w-3 mr-1" />
                Guardrails Passed
              </Badge>
            ) : (
              <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200 ml-2">
                <ShieldAlert className="h-3 w-3 mr-1" />
                Guardrails Failed
              </Badge>
            )}
          </CardTitle>
        </div>
        <CardDescription className="flex items-center gap-4 text-xs">
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {email.generation_time_ms ? `${(email.generation_time_ms / 1000).toFixed(1)}s` : '—'}
          </span>
          {email.attempt_number > 1 && (
            <span className="flex items-center gap-1">
              <RefreshCw className="h-3 w-3" />
              {email.attempt_number} attempts
            </span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Gmail-style email preview */}
        <div className="rounded-lg border bg-white shadow-soft overflow-hidden">
          {/* Email header bar */}
          <div className="border-b bg-purple-50/80 px-6 py-3">
            <p className="text-sm font-semibold text-purple-900">{email.subject}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              From: AussieLoanAI Retention Team &lt;alternatives@aussieloanai.com.au&gt;
            </p>
          </div>
          {/* Email body */}
          <div className="px-6 py-5 text-sm leading-relaxed">
            <HtmlEmailBody html={htmlContent} />
          </div>
        </div>

        {/* Unified Compliance Checks */}
        {email.guardrail_results && email.guardrail_results.length > 0 && (
          <GuardrailLogDisplay checks={email.guardrail_results} />
        )}
      </CardContent>
    </Card>
  )
}
