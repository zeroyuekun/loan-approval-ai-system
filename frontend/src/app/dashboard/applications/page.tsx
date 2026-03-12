'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useApplications } from '@/hooks/useApplications'
import { ApplicationTable } from '@/components/applications/ApplicationTable'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectItem } from '@/components/ui/select'
import { Plus, Search } from 'lucide-react'

export default function ApplicationsPage() {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [purposeFilter, setPurposeFilter] = useState('')

  const { data, isLoading } = useApplications({
    page,
    search: search || undefined,
    status: statusFilter || undefined,
    purpose: purposeFilter || undefined,
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-1 gap-2">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search applications..."
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1) }}
              className="pl-9"
            />
          </div>
          <Select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
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
          >
            <SelectItem value="">All Purposes</SelectItem>
            <SelectItem value="home">Home</SelectItem>
            <SelectItem value="auto">Auto</SelectItem>
            <SelectItem value="education">Education</SelectItem>
            <SelectItem value="personal">Personal</SelectItem>
            <SelectItem value="business">Business</SelectItem>
          </Select>
        </div>
        <Link href="/dashboard/applications/new">
          <Button>
            <Plus className="mr-2 h-4 w-4" />
            New Application
          </Button>
        </Link>
      </div>

      <ApplicationTable
        applications={data?.results || []}
        isLoading={isLoading}
        totalCount={data?.count || 0}
        page={page}
        onPageChange={setPage}
      />
    </div>
  )
}
