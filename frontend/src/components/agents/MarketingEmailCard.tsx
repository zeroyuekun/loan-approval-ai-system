'use client'

import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { MarketingEmail } from '@/types'
import { ShieldCheck, ShieldAlert, Clock, Star, Reply, Forward, MoreVertical, RefreshCw } from 'lucide-react'
import { GuardrailLogDisplay } from '@/components/emails/GuardrailLogDisplay'
import { HtmlEmailBody } from '@/components/emails/EmailPreview'
import { renderEmailHtml } from '@/lib/emailHtmlRenderer'

function formatTime() {
  const now = new Date()
  const hours = now.getHours()
  const minutes = now.getMinutes().toString().padStart(2, '0')
  const ampm = hours >= 12 ? 'PM' : 'AM'
  const h = hours % 12 || 12
  return `${h}:${minutes} ${ampm}`
}

interface MarketingEmailCardProps {
  email: MarketingEmail
}

export function MarketingEmailCard({ email }: MarketingEmailCardProps) {
  const htmlContent = email.html_body || renderEmailHtml(email.body, 'marketing')
  const senderName = 'Sarah Mitchell'
  const senderEmail = 'alternatives@aussieloanai.com.au'

  return (
    <Card className="overflow-hidden">
      <CardContent className="p-0">
        {/* Gmail-style email view */}
        <div className="bg-white rounded-lg">
          {/* Subject bar */}
          <div className="flex items-center justify-between px-4 py-3 border-b">
            <div className="flex items-center gap-3 min-w-0">
              <h2 className="text-lg font-normal text-gray-900 truncate">
                {email.subject}
              </h2>
              <Badge className="bg-purple-100 text-purple-700 border-purple-200 shrink-0" variant="outline">
                Marketing
              </Badge>
              {email.passed_guardrails ? (
                <Badge className="bg-green-100 text-green-700 border-green-200 shrink-0" variant="outline">
                  <ShieldCheck className="mr-1 h-3 w-3" />
                  Passed
                </Badge>
              ) : (
                <Badge className="bg-red-100 text-red-700 border-red-200 shrink-0" variant="outline">
                  <ShieldAlert className="mr-1 h-3 w-3" />
                  Failed
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-1 text-gray-400 shrink-0">
              <button className="p-1.5 hover:bg-gray-100 rounded-full" aria-label="More">
                <MoreVertical className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Sender info row */}
          <div className="flex items-start gap-3 px-4 py-3">
            {/* Avatar circle — purple for marketing */}
            <div className="h-10 w-10 rounded-full bg-purple-600 flex items-center justify-center text-white font-medium text-sm shrink-0 mt-0.5">
              S
            </div>

            {/* Sender details */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm text-gray-900">{senderName}</span>
                  <span className="text-xs text-gray-500">&lt;{senderEmail}&gt;</span>
                </div>
                <div className="flex items-center gap-2 text-xs text-gray-500 shrink-0">
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {email.generation_time_ms ? `${(email.generation_time_ms / 1000).toFixed(1)}s` : '—'}
                  </span>
                  {email.attempt_number > 1 && (
                    <span className="flex items-center gap-1">
                      <RefreshCw className="h-3 w-3" />
                      {email.attempt_number}
                    </span>
                  )}
                  <span>{formatTime()}</span>
                  <Star className="h-4 w-4 text-gray-300 hover:text-yellow-400 cursor-pointer" />
                </div>
              </div>
              <p className="text-xs text-gray-500 mt-0.5">
                to applicant
              </p>
            </div>
          </div>

          {/* Email body */}
          <div className="px-4 pb-2 pl-[68px]">
            <div className="text-sm leading-relaxed text-gray-800">
              <HtmlEmailBody html={htmlContent} />
            </div>
          </div>

          {/* Reply / Forward bar */}
          <div className="flex items-center gap-2 px-4 pl-[68px] pb-4">
            <button className="flex items-center gap-1.5 rounded-full border border-gray-300 px-4 py-1.5 text-xs text-gray-700 hover:bg-gray-50">
              <Reply className="h-3.5 w-3.5" />
              Reply
            </button>
            <button className="flex items-center gap-1.5 rounded-full border border-gray-300 px-4 py-1.5 text-xs text-gray-700 hover:bg-gray-50">
              <Forward className="h-3.5 w-3.5" />
              Forward
            </button>
          </div>
        </div>

        {/* Guardrail checks below the email */}
        {email.guardrail_results && email.guardrail_results.length > 0 && (
          <div className="border-t px-4 py-4">
            <GuardrailLogDisplay checks={email.guardrail_results} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}
