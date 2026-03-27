'use client'

import { useRouter } from 'next/navigation'
import { Badge } from '@/components/ui/badge'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { LoanApplication } from '@/types'
import { formatCurrency, formatDate, getDisplayStatus } from '@/lib/utils'
import { ChevronLeft, ChevronRight } from 'lucide-react'

interface ApplicationTableProps {
  applications: LoanApplication[]
  isLoading: boolean
  totalCount: number
  page: number
  onPageChange: (page: number) => void
  pageSize?: number
}

export function ApplicationTable({
  applications,
  isLoading,
  totalCount,
  page,
  onPageChange,
  pageSize = 20,
}: ApplicationTableProps) {
  const router = useRouter()
  const totalPages = Math.ceil(totalCount / pageSize)

  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    )
  }

  return (
    <div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>ID</TableHead>
            <TableHead>Applicant</TableHead>
            <TableHead>Amount</TableHead>
            <TableHead>Credit Score</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Date</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {applications.map((app) => (
            <TableRow
              key={app.id}
              className="cursor-pointer"
              onClick={() => router.push(`/dashboard/applications/${app.id}`)}
            >
              <TableCell className="font-mono text-xs">{app.id.slice(0, 8)}</TableCell>
              <TableCell className="font-medium">
                {app.applicant.first_name} {app.applicant.last_name}
              </TableCell>
              <TableCell>{formatCurrency(app.loan_amount)}</TableCell>
              <TableCell>{app.credit_score}</TableCell>
              <TableCell>
                {(() => { const s = getDisplayStatus(app.status, app.decision); return (
                  <Badge className={s.color} variant="outline">{s.label}</Badge>
                ) })()}
              </TableCell>
              <TableCell className="text-muted-foreground">{formatDate(app.created_at)}</TableCell>
            </TableRow>
          ))}
          {applications.length === 0 && (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                No applications found
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-sm text-muted-foreground">
            Showing {((page - 1) * pageSize) + 1} to {Math.min(page * pageSize, totalCount)} of {totalCount}
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="bg-white hover:bg-slate-50 disabled:bg-white disabled:opacity-100 disabled:text-muted-foreground/40"
              onClick={() => onPageChange(page - 1)}
              disabled={page <= 1}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-sm">
              Page {page} of {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              className="bg-white hover:bg-slate-50 disabled:bg-white disabled:opacity-100 disabled:text-muted-foreground/40"
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
