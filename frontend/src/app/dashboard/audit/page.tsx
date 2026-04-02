'use client'

import { Fragment, useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { auditApi } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectItem } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Search, ChevronDown, ChevronRight, Loader2 } from 'lucide-react'

const ACTION_OPTIONS = [
  { value: '', label: 'All Actions' },
  { value: 'loan_created', label: 'Loan Created' },
  { value: 'loan_updated', label: 'Loan Updated' },
  { value: 'prediction_run', label: 'Prediction Run' },
  { value: 'model_trained', label: 'Model Trained' },
  { value: 'pipeline_completed', label: 'Pipeline Completed' },
  { value: 'pipeline_failed', label: 'Pipeline Failed' },
]

const RESOURCE_TYPE_OPTIONS = [
  { value: '', label: 'All Types' },
  { value: 'LoanApplication', label: 'LoanApplication' },
  { value: 'ModelVersion', label: 'ModelVersion' },
]

function formatAction(action: string): string {
  return action
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function getActionBadgeVariant(action: string) {
  switch (action) {
    case 'loan_created':
    case 'pipeline_completed':
      return 'success' as const
    case 'loan_updated':
      return 'default' as const
    case 'prediction_run':
      return 'secondary' as const
    case 'model_trained':
      return 'warning' as const
    case 'pipeline_failed':
      return 'destructive' as const
    default:
      return 'outline' as const
  }
}

export default function AuditPage() {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [resourceTypeFilter, setResourceTypeFilter] = useState('')
  const [expandedRow, setExpandedRow] = useState<string | null>(null)

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search)
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  const params: Record<string, string | number> = { page }
  if (debouncedSearch) params.search = debouncedSearch
  if (actionFilter) params.action = actionFilter
  if (resourceTypeFilter) params.resource_type = resourceTypeFilter

  const { data, isLoading, isError } = useQuery({
    queryKey: ['audit-logs', params],
    queryFn: () => auditApi.list(params).then((res) => res.data),
  })

  const results = data?.results ?? []
  const totalCount = data?.count ?? 0
  const pageSize = 10
  const totalPages = Math.ceil(totalCount / pageSize)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Audit Log</h1>
        <p className="text-muted-foreground">Track all system actions and changes</p>
      </div>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search by resource ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select
          value={actionFilter}
          onChange={(e) => { setActionFilter(e.target.value); setPage(1) }}
        >
          {ACTION_OPTIONS.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
          ))}
        </Select>
        <Select
          value={resourceTypeFilter}
          onChange={(e) => { setResourceTypeFilter(e.target.value); setPage(1) }}
        >
          {RESOURCE_TYPE_OPTIONS.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
          ))}
        </Select>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Events</span>
            <span className="text-sm font-normal text-muted-foreground">{totalCount} total</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : isError ? (
            <div className="text-center py-12 text-destructive">Failed to load audit logs. Please refresh.</div>
          ) : results.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">No audit log entries found.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-3 pr-4 font-medium w-8"></th>
                    <th className="pb-3 pr-4 font-medium">Time</th>
                    <th className="pb-3 pr-4 font-medium">User</th>
                    <th className="pb-3 pr-4 font-medium">Action</th>
                    <th className="pb-3 pr-4 font-medium">Resource Type</th>
                    <th className="pb-3 pr-4 font-medium">Resource ID</th>
                    <th className="pb-3 font-medium">IP Address</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((entry: any) => {
                    const isExpanded = expandedRow === entry.id
                    return (
                      <Fragment key={entry.id}>
                        <tr
                          className="border-b cursor-pointer hover:bg-muted/50 transition-colors"
                          onClick={() => setExpandedRow(isExpanded ? null : entry.id)}
                        >
                          <td className="py-3 pr-4">
                            {isExpanded
                              ? <ChevronDown className="h-4 w-4 text-muted-foreground" />
                              : <ChevronRight className="h-4 w-4 text-muted-foreground" />
                            }
                          </td>
                          <td className="py-3 pr-4 whitespace-nowrap">
                            {new Date(entry.timestamp).toLocaleString()}
                          </td>
                          <td className="py-3 pr-4">{entry.username ?? 'System'}</td>
                          <td className="py-3 pr-4">
                            <Badge variant={getActionBadgeVariant(entry.action)}>
                              {formatAction(entry.action)}
                            </Badge>
                          </td>
                          <td className="py-3 pr-4">{entry.resource_type}</td>
                          <td className="py-3 pr-4 font-mono text-xs max-w-[200px] truncate" title={entry.resource_id}>
                            {entry.resource_id}
                          </td>
                          <td className="py-3">{entry.ip_address ?? '-'}</td>
                        </tr>
                        {isExpanded && (
                          <tr className="border-b bg-muted/30">
                            <td></td>
                            <td colSpan={6} className="py-3 px-4">
                              <div className="text-xs">
                                <span className="font-medium text-muted-foreground">Details:</span>
                                <pre className="mt-1 p-3 rounded-lg bg-slate-50 border text-xs overflow-x-auto">
                                  {JSON.stringify(entry.details, null, 2)}
                                </pre>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {totalPages > 1 && (
            <div className="flex items-center justify-between pt-4">
              <p className="text-sm text-muted-foreground">
                Page {page} of {totalPages}
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage(page - 1)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage(page + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

