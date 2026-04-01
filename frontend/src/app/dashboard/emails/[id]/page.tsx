'use client'

import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { authApi } from '@/lib/api'
import { CustomerActivity, GeneratedEmail } from '@/types'
import { EmailPreview } from '@/components/emails/EmailPreview'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { ArrowLeft, Mail, FileText, ChevronRight } from 'lucide-react'
import { formatDate } from '@/lib/utils'

interface ApplicationGroup {
  application_id: string
  emails: GeneratedEmail[]
  latestDate: string
  passedCount: number
  failedCount: number
}

function groupByApplication(emails: GeneratedEmail[]): ApplicationGroup[] {
  const map = new Map<string, ApplicationGroup>()
  for (const email of emails) {
    const appId = email.application_id
    if (!map.has(appId)) {
      map.set(appId, { application_id: appId, emails: [], latestDate: email.created_at, passedCount: 0, failedCount: 0 })
    }
    const group = map.get(appId)!
    group.emails.push(email)
    if (email.passed_guardrails) group.passedCount++
    else group.failedCount++
    if (email.created_at > group.latestDate) group.latestDate = email.created_at
  }
  // Sort by latest date descending
  return Array.from(map.values()).sort((a, b) => b.latestDate.localeCompare(a.latestDate))
}

export default function CustomerEmailsPage() {
  const params = useParams()
  const router = useRouter()
  const customerId = Number(params.id)

  const { data: activity, isLoading } = useQuery<CustomerActivity>({
    queryKey: ['customerActivity', customerId],
    queryFn: async () => {
      const { data } = await authApi.getCustomerActivity(customerId)
      return data
    },
    enabled: !isNaN(customerId),
  })

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-48" />
        ))}
      </div>
    )
  }

  const emails = activity?.emails || []
  const customerName = activity?.customer_name || 'Unknown'
  const applicationGroups = groupByApplication(emails)
  const hasMultipleApplications = applicationGroups.length > 1

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => router.push('/dashboard/emails')}
          className="rounded-lg p-2 hover:bg-muted transition-colors"
        >
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{customerName}</h1>
          <p className="text-muted-foreground">
            {emails.length} generated email{emails.length !== 1 ? 's' : ''}
            {hasMultipleApplications && ` across ${applicationGroups.length} applications`}
          </p>
        </div>
      </div>

      {emails.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <Mail className="h-10 w-10 mb-3" />
            <p>No emails generated for this client yet</p>
          </CardContent>
        </Card>
      ) : hasMultipleApplications ? (
        // Grouped by application
        applicationGroups.map((group) => (
          <Card key={group.application_id}>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-100">
                    <FileText className="h-4 w-4 text-blue-600" />
                  </div>
                  <div>
                    <CardTitle className="text-sm flex items-center gap-2">
                      Application {group.application_id.slice(0, 8)}
                      <Link
                        href={`/dashboard/applications/${group.application_id}`}
                        className="text-xs text-blue-600 hover:underline font-normal"
                      >
                        View application
                        <ChevronRight className="inline h-3 w-3" />
                      </Link>
                    </CardTitle>
                    <CardDescription className="text-xs">
                      {group.emails.length} email{group.emails.length !== 1 ? 's' : ''} &middot; Last: {formatDate(group.latestDate)}
                    </CardDescription>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200 text-xs">
                    {group.passedCount} Passed
                  </Badge>
                  {group.failedCount > 0 && (
                    <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200 text-xs">
                      {group.failedCount} Failed
                    </Badge>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent className="pt-0 space-y-4">
              {group.emails.map((email) => (
                <EmailPreview key={email.id} email={email} />
              ))}
            </CardContent>
          </Card>
        ))
      ) : (
        // Single application — no extra grouping needed
        <div className="space-y-4">
          {emails.map((email) => (
            <EmailPreview key={email.id} email={email} />
          ))}
        </div>
      )}
    </div>
  )
}
