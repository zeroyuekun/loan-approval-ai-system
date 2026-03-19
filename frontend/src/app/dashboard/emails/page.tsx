'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { GeneratedEmail, PaginatedResponse } from '@/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { Mail, ChevronRight, Search } from 'lucide-react'
import { formatDate } from '@/lib/utils'

interface CustomerGroup {
  applicant_id: number
  applicant_name: string
  emailCount: number
  passedCount: number
  failedCount: number
  latestDate: string
}

function groupByCustomer(emails: GeneratedEmail[]): CustomerGroup[] {
  const map = new Map<number, CustomerGroup>()
  for (const email of emails) {
    const id = email.applicant_id ?? 0
    const name = email.applicant_name ?? 'Unknown'
    if (!map.has(id)) {
      map.set(id, { applicant_id: id, applicant_name: name, emailCount: 0, passedCount: 0, failedCount: 0, latestDate: email.created_at })
    }
    const group = map.get(id)!
    group.emailCount++
    if (email.passed_guardrails) group.passedCount++
    else group.failedCount++
    if (email.created_at > group.latestDate) group.latestDate = email.created_at
  }
  return Array.from(map.values()).sort((a, b) => a.applicant_name.localeCompare(b.applicant_name))
}

export default function EmailsPage() {
  const [search, setSearch] = useState('')
  const { data, isLoading } = useQuery<PaginatedResponse<GeneratedEmail>>({
    queryKey: ['emails'],
    queryFn: async () => {
      const { data } = await api.get('/emails/', { params: { page_size: 100 } })
      return data
    },
  })

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-16" />
        ))}
      </div>
    )
  }

  const emails = data?.results || []

  if (emails.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-center space-y-2">
          <Mail className="h-12 w-12 mx-auto text-muted-foreground" />
          <p className="text-muted-foreground">No generated emails yet</p>
          <p className="text-sm text-muted-foreground">
            Emails are generated when the AI pipeline processes a loan application
          </p>
        </div>
      </div>
    )
  }

  const customerGroups = groupByCustomer(emails)
  const filtered = search.trim()
    ? customerGroups.filter((g) => g.applicant_name.toLowerCase().includes(search.toLowerCase()))
    : customerGroups

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Generated Emails</h1>
        <p className="text-muted-foreground">Select a client to view their email history</p>
      </div>

      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search clients..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Mail className="h-4 w-4" />
            {filtered.length} Client{filtered.length !== 1 ? 's' : ''}
            {search.trim() && filtered.length !== customerGroups.length && (
              <span className="text-xs font-normal text-muted-foreground">
                (of {customerGroups.length})
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="divide-y border-t">
            {filtered.length === 0 && (
              <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
                No clients matching &ldquo;{search}&rdquo;
              </div>
            )}
            {filtered.map((group) => (
              <Link
                key={group.applicant_id}
                href={`/dashboard/emails/${group.applicant_id}`}
                className="flex items-center gap-4 px-6 py-4 hover:bg-muted/50 transition-colors"
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 text-sm font-semibold text-white shrink-0">
                  {group.applicant_name.charAt(0).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate">{group.applicant_name}</p>
                  <p className="text-xs text-muted-foreground">
                    {group.emailCount} email{group.emailCount !== 1 ? 's' : ''} &middot; Last: {formatDate(group.latestDate)}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200 text-xs">
                    {group.passedCount} passed
                  </Badge>
                  {group.failedCount > 0 && (
                    <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200 text-xs">
                      {group.failedCount} failed
                    </Badge>
                  )}
                </div>
                <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
              </Link>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
