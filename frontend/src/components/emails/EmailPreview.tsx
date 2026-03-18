'use client'

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { GeneratedEmail } from '@/types'
import { GuardrailLogDisplay } from './GuardrailLogDisplay'
import { CheckCircle, XCircle, Clock } from 'lucide-react'

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
            <div className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{email.body}</div>
          </div>
        </div>

        {email.guardrail_checks && email.guardrail_checks.length > 0 && (
          <GuardrailLogDisplay checks={email.guardrail_checks} />
        )}
      </CardContent>
    </Card>
  )
}
