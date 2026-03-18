'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { AgentRun, PaginatedResponse } from '@/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/utils'
import { Bot, ChevronRight, Search } from 'lucide-react'

interface CustomerGroup {
  applicant_id: number
  applicant_name: string
  runCount: number
  completedCount: number
  failedCount: number
  escalatedCount: number
  latestDate: string
}

function groupByCustomer(runs: AgentRun[]): CustomerGroup[] {
  const map = new Map<number, CustomerGroup>()
  for (const run of runs) {
    const id = run.applicant_id ?? 0
    const name = run.applicant_name ?? 'Unknown'
    if (!map.has(id)) {
      map.set(id, { applicant_id: id, applicant_name: name, runCount: 0, completedCount: 0, failedCount: 0, escalatedCount: 0, latestDate: run.created_at })
    }
    const group = map.get(id)!
    group.runCount++
    if (run.status === 'completed') group.completedCount++
    if (run.status === 'failed') group.failedCount++
    if (run.status === 'escalated') group.escalatedCount++
    if (run.created_at > group.latestDate) group.latestDate = run.created_at
  }
  return Array.from(map.values()).sort((a, b) => a.applicant_name.localeCompare(b.applicant_name))
}

export default function AgentsPage() {
  const { data, isLoading } = useQuery<PaginatedResponse<AgentRun>>({
    queryKey: ['agentRuns'],
    queryFn: async () => {
      const { data } = await api.get('/agents/runs/', { params: { page_size: 100 } })
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

  const runs = data?.results || []

  if (runs.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-center space-y-2">
          <Bot className="h-12 w-12 mx-auto text-muted-foreground" />
          <p className="text-muted-foreground">No agent workflows yet</p>
          <p className="text-sm text-muted-foreground">
            Agent workflows are triggered when you run the AI pipeline on a loan application
          </p>
        </div>
      </div>
    )
  }

  const [search, setSearch] = useState('')
  const customerGroups = groupByCustomer(runs)
  const filtered = search.trim()
    ? customerGroups.filter((g) => g.applicant_name.toLowerCase().includes(search.toLowerCase()))
    : customerGroups

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Agent Workflows</h1>
        <p className="text-muted-foreground">Select a client to view their workflow history</p>
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
            <Bot className="h-4 w-4" />
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
                href={`/dashboard/agents/${group.applicant_id}`}
                className="flex items-center gap-4 px-6 py-4 hover:bg-muted/50 transition-colors"
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-violet-500 to-purple-600 text-sm font-semibold text-white shrink-0">
                  {group.applicant_name.charAt(0).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate">{group.applicant_name}</p>
                  <p className="text-xs text-muted-foreground">
                    {group.runCount} workflow{group.runCount !== 1 ? 's' : ''} &middot; Last: {formatDate(group.latestDate)}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
                  {group.completedCount > 0 && (
                    <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200 text-xs">
                      {group.completedCount} completed
                    </Badge>
                  )}
                  {group.failedCount > 0 && (
                    <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200 text-xs">
                      {group.failedCount} failed
                    </Badge>
                  )}
                  {group.escalatedCount > 0 && (
                    <Badge variant="outline" className="bg-purple-50 text-purple-700 border-purple-200 text-xs">
                      {group.escalatedCount} escalated
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
