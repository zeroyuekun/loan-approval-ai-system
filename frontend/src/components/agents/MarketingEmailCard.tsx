'use client'

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { MarketingEmail } from '@/types'
import { Mail, ShieldCheck, ShieldAlert, Clock, RefreshCw } from 'lucide-react'
import { GuardrailLogDisplay } from '@/components/emails/GuardrailLogDisplay'
import { FormattedEmailBody } from '@/components/emails/EmailPreview'

interface MarketingEmailCardProps {
  email: MarketingEmail
}

export function MarketingEmailCard({ email }: MarketingEmailCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Mail className="h-4 w-4 text-purple-600" />
          Marketing Follow-up Email
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
        {/* Email Preview */}
        <div className="rounded-lg border bg-purple-50/30 p-5">
          <div className="mb-3 pb-3 border-b border-purple-200/50">
            <div className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground font-medium">Subject:</span>
              <span className="font-semibold text-purple-900">{email.subject}</span>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1">
              <span>From: The AussieLoanAI Retention Team &lt;alternatives@aussieloanai.com.au&gt;</span>
            </div>
          </div>
          <div className="text-sm text-foreground/90 whitespace-pre-line leading-relaxed">
            <FormattedEmailBody body={email.body} />
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
