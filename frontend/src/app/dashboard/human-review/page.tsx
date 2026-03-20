'use client'

import { useState } from 'react'
import { useEscalatedRuns, useSubmitReview } from '@/hooks/useHumanReview'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/utils'
import { ChevronLeft, ChevronRight, ShieldAlert, CheckCircle2, XCircle, RotateCcw, AlertTriangle } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { AgentRun } from '@/types'

function ReviewActionModal({
  run,
  onClose,
  onSuccess,
}: {
  run: AgentRun
  onClose: () => void
  onSuccess: () => void
}) {
  const [action, setAction] = useState<'approve' | 'deny' | 'regenerate' | null>(null)
  const [note, setNote] = useState('')
  const submitReview = useSubmitReview()

  const handleSubmit = () => {
    if (!action) return
    submitReview.mutate(
      { runId: run.id, action, note: note || undefined },
      {
        onSuccess: () => {
          onSuccess()
          onClose()
        },
      }
    )
  }

  const biasReport = run.bias_reports?.find((br) => br.flagged || br.requires_human_review)

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !submitReview.isPending) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Review Escalated Application</DialogTitle>
          <DialogDescription>
            Application {run.application_id.slice(0, 8)} &mdash; {run.applicant_name ?? 'Unknown Applicant'}
          </DialogDescription>
        </DialogHeader>

        {biasReport && (
          <div className="rounded-lg border border-amber-200 bg-amber-50/50 px-4 py-3">
            <div className="flex items-start gap-3">
              <AlertTriangle className="h-5 w-5 text-amber-600 mt-0.5 shrink-0" />
              <div className="space-y-1">
                <p className="text-sm font-medium text-amber-900">Bias Detection Flag</p>
                <p className="text-sm text-amber-800">
                  Score: <span className="font-mono font-semibold">{biasReport.bias_score.toFixed(1)}</span>
                  {biasReport.categories.length > 0 && (
                    <> &mdash; Categories: {biasReport.categories.join(', ')}</>
                  )}
                </p>
                <p className="text-xs text-amber-700 mt-1">{biasReport.analysis}</p>
              </div>
            </div>
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium mb-2 block">Decision</label>
            <div className="flex gap-2">
              <Button
                variant={action === 'approve' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setAction('approve')}
                disabled={submitReview.isPending}
                className={action === 'approve' ? 'bg-green-600 hover:bg-green-700' : ''}
              >
                <CheckCircle2 className="mr-1.5 h-4 w-4" />
                Approve
              </Button>
              <Button
                variant={action === 'deny' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setAction('deny')}
                disabled={submitReview.isPending}
                className={action === 'deny' ? 'bg-red-600 hover:bg-red-700' : ''}
              >
                <XCircle className="mr-1.5 h-4 w-4" />
                Deny
              </Button>
              <Button
                variant={action === 'regenerate' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setAction('regenerate')}
                disabled={submitReview.isPending}
                className={action === 'regenerate' ? 'bg-blue-600 hover:bg-blue-700' : ''}
              >
                <RotateCcw className="mr-1.5 h-4 w-4" />
                Regenerate
              </Button>
            </div>
          </div>

          <div>
            <label htmlFor="review-note" className="text-sm font-medium mb-2 block">
              Reviewer Note <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <textarea
              id="review-note"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              rows={3}
              placeholder="Add context for your decision..."
              value={note}
              onChange={(e) => setNote(e.target.value)}
              disabled={submitReview.isPending}
            />
          </div>

          {submitReview.isError && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              Submission failed. Please try again.
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={submitReview.isPending}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!action || submitReview.isPending}
          >
            {submitReview.isPending ? 'Submitting...' : 'Submit Review'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default function HumanReviewPage() {
  const [page, setPage] = useState(1)
  const [selectedRun, setSelectedRun] = useState<AgentRun | null>(null)
  const router = useRouter()

  const { data, isLoading, isError } = useEscalatedRuns({ page })

  const runs = data?.results || []
  const totalCount = data?.count || 0
  const pageSize = 20
  const totalPages = Math.ceil(totalCount / pageSize)

  const handleReviewSuccess = () => {
    setSelectedRun(null)
    // Reset to page 1 after review to avoid stale page index
    if (page > 1 && runs.length <= 1) {
      setPage(1)
    }
  }

  return (
    <div className="space-y-6">
      <Card className="border-amber-200/60 bg-gradient-to-r from-amber-50/50 to-orange-50/30">
        <CardContent className="flex items-center gap-3 py-4">
          <ShieldAlert className="h-5 w-5 text-amber-600" />
          <div>
            <p className="text-sm font-medium text-amber-900">
              {totalCount} application{totalCount !== 1 ? 's' : ''} awaiting human review
            </p>
            <p className="text-xs text-amber-700">
              These applications were flagged by the bias detection system or have borderline ML predictions.
            </p>
          </div>
        </CardContent>
      </Card>

      {isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Failed to load escalated applications. Please refresh the page.
        </div>
      )}

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : (
        <div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Application</TableHead>
                <TableHead>Applicant</TableHead>
                <TableHead>Bias Score</TableHead>
                <TableHead>Categories</TableHead>
                <TableHead>Escalated</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((run) => {
                const biasReport = run.bias_reports?.find(
                  (br) => br.flagged || br.requires_human_review
                )
                return (
                  <TableRow key={run.id}>
                    <TableCell
                      className="font-mono text-xs cursor-pointer hover:text-blue-600"
                      onClick={() => router.push(`/dashboard/applications/${run.application_id}`)}
                    >
                      {run.application_id.slice(0, 8)}
                    </TableCell>
                    <TableCell className="font-medium">
                      {run.applicant_name ?? 'Unknown'}
                    </TableCell>
                    <TableCell>
                      {biasReport ? (
                        <Badge
                          variant="outline"
                          className={
                            biasReport.bias_score > 80
                              ? 'bg-red-100 text-red-800'
                              : biasReport.bias_score > 60
                              ? 'bg-amber-100 text-amber-800'
                              : 'bg-yellow-100 text-yellow-800'
                          }
                        >
                          {biasReport.bias_score.toFixed(1)}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground text-xs">N/A</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1 flex-wrap">
                        {biasReport?.categories.length ? (
                          biasReport.categories.map((cat) => (
                            <Badge key={cat} variant="outline" className="text-xs bg-slate-100">
                              {cat}
                            </Badge>
                          ))
                        ) : (
                          <span className="text-muted-foreground text-xs">&mdash;</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {formatDate(run.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" onClick={() => setSelectedRun(run)}>
                        Review
                      </Button>
                    </TableCell>
                  </TableRow>
                )
              })}
              {runs.length === 0 && !isError && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-12">
                    <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-green-500" />
                    <p className="font-medium">All clear</p>
                    <p className="text-sm">No applications require human review at this time.</p>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>

          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-muted-foreground">
                Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, totalCount)} of {totalCount}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage(page - 1)}
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
                  onClick={() => setPage(page + 1)}
                  disabled={page >= totalPages}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {selectedRun && (
        <ReviewActionModal
          run={selectedRun}
          onClose={() => setSelectedRun(null)}
          onSuccess={handleReviewSuccess}
        />
      )}
    </div>
  )
}
