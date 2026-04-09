'use client'

import { useMemo } from 'react'
import DOMPurify from 'dompurify'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { GeneratedEmail } from '@/types'
import { GuardrailLogDisplay } from './GuardrailLogDisplay'
import { CheckCircle, XCircle, Clock, Star, Reply, Forward, MoreVertical, Paperclip } from 'lucide-react'

export function HtmlEmailBody({ html }: { html: string }) {
  // Content is sanitized with DOMPurify before rendering — safe against XSS
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

function formatTime() {
  const now = new Date()
  const hours = now.getHours()
  const minutes = now.getMinutes().toString().padStart(2, '0')
  const ampm = hours >= 12 ? 'PM' : 'AM'
  const h = hours % 12 || 12
  return `${h}:${minutes} ${ampm}`
}

interface EmailPreviewProps {
  email: GeneratedEmail
}

export function EmailPreview({ email }: EmailPreviewProps) {
  const htmlContent = useMemo(() => email.html_body || plainTextToHtml(email.body), [email.html_body, email.body])
  const isApproval = email.decision === 'approved'
  const senderInitial = 'S'
  const senderName = 'Sarah Mitchell'
  const senderEmail = 'decisions@aussieloanai.com.au'
  const hasAttachments = isApproval

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
              {email.passed_guardrails ? (
                <Badge className="bg-green-100 text-green-700 border-green-200 shrink-0" variant="outline">
                  <CheckCircle className="mr-1 h-3 w-3" />
                  Passed
                </Badge>
              ) : (
                <Badge className="bg-red-100 text-red-700 border-red-200 shrink-0" variant="outline">
                  <XCircle className="mr-1 h-3 w-3" />
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
            {/* Avatar circle */}
            <div className="h-10 w-10 rounded-full bg-blue-600 flex items-center justify-center text-white font-medium text-sm shrink-0 mt-0.5">
              {senderInitial}
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
                    {email.generation_time_ms}ms
                  </span>
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

          {/* Attachments — approval emails have loan documents */}
          {hasAttachments && (
            <div className="px-4 pl-[68px] pb-4">
              <div className="flex flex-wrap gap-2 mt-2">
                {[
                  'Loan Contract.pdf',
                  'Key Facts Sheet.pdf',
                  'Credit Guide.pdf',
                ].map((name) => (
                  <div
                    key={name}
                    className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600"
                  >
                    <Paperclip className="h-3.5 w-3.5 text-gray-400" />
                    <span>{name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

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
        {email.guardrail_checks && email.guardrail_checks.length > 0 && (
          <div className="border-t px-4 py-4">
            <GuardrailLogDisplay checks={email.guardrail_checks} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}
