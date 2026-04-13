'use client'

import { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import { useApplications } from '@/hooks/useApplications'
import { ApplicationTable } from '@/components/applications/ApplicationTable'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectItem } from '@/components/ui/select'
import { Search, Loader2, FileX } from 'lucide-react'
import { agentsApi } from '@/lib/api'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

export default function ApplicationsPage() {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [purposeFilter, setPurposeFilter] = useState('')
  const [checkAllState, setCheckAllState] = useState<'idle' | 'loading' | 'done'>('idle')
  const [checkAllResult, setCheckAllResult] = useState<{ queued: number } | null>(null)
  const queryClient = useQueryClient()
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([])

  // Clean up timers on unmount
  useEffect(() => {
    return () => timersRef.current.forEach(clearTimeout)
  }, [])

  // Debounce search input by 300ms
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search)
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [search])

  const { data, isLoading } = useApplications({
    page,
    search: debouncedSearch || undefined,
    status: statusFilter || undefined,
    purpose: purposeFilter || undefined,
  })

  const handleCheckAll = async () => {
    setCheckAllState('loading')
    setCheckAllResult(null)
    try {
      const { data } = await agentsApi.orchestrateAll(true)
      setCheckAllResult({ queued: data.queued })
      setCheckAllState('done')
      // Refresh the applications list after a short delay
      timersRef.current.push(setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['applications'] })
      }, 2000))
      // Reset the button after 5 seconds
      timersRef.current.push(setTimeout(() => {
        setCheckAllState('idle')
        setCheckAllResult(null)
      }, 5000))
    } catch {
      toast.error('Failed to process applications. Please try again.')
      setCheckAllState('idle')
      setCheckAllResult(null)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-1 gap-2">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <Input
              placeholder="Search applications..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
              aria-label="Search applications by name or reference"
            />
          </div>
          <Select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
            aria-label="Filter by application status"
          >
            <SelectItem value="">All Statuses</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="processing">Processing</SelectItem>
            <SelectItem value="approved">Approved</SelectItem>
            <SelectItem value="denied">Denied</SelectItem>
            <SelectItem value="review">Review</SelectItem>
          </Select>
          <Select
            value={purposeFilter}
            onChange={(e) => { setPurposeFilter(e.target.value); setPage(1) }}
            aria-label="Filter by loan purpose"
          >
            <SelectItem value="">All Purposes</SelectItem>
            <SelectItem value="home">Home</SelectItem>
            <SelectItem value="auto">Auto</SelectItem>
            <SelectItem value="education">Education</SelectItem>
            <SelectItem value="personal">Personal</SelectItem>
            <SelectItem value="business">Business</SelectItem>
          </Select>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={handleCheckAll}
            disabled={checkAllState === 'loading'}
            className="hover:opacity-90"
          >
            {checkAllState === 'loading' ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Processing...
              </>
            ) : checkAllState === 'done' ? (
              checkAllResult?.queued
                ? `${checkAllResult.queued} queued`
                : 'No pending apps'
            ) : (
              'Check All'
            )}
          </Button>
          <Link href="/dashboard/applications/new">
            <Button className="hover:opacity-90">
              New Application
            </Button>
          </Link>
        </div>
      </div>

      <ApplicationTable
        applications={data?.results || []}
        isLoading={isLoading}
        totalCount={data?.count || 0}
        page={page}
        onPageChange={setPage}
      />

      {!isLoading && data && data.results?.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
          <FileX className="h-10 w-10 mb-3" aria-hidden="true" />
          <p className="text-sm font-medium">No applications found</p>
          <p className="text-xs mt-1">Try adjusting your search or filters.</p>
        </div>
      )}
    </div>
  )
}
