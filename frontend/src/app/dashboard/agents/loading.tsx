import { Skeleton } from '@/components/ui/skeleton'

export default function AgentsLoading() {
  return (
    <div className="space-y-6">
      {/* Page title */}
      <div className="space-y-1">
        <Skeleton className="h-8 w-48 rounded-xl" />
        <Skeleton className="h-5 w-72 rounded-xl" />
      </div>
      {/* Search bar */}
      <Skeleton className="h-10 w-full rounded-xl" />
      {/* Client cards */}
      <Skeleton className="h-12 w-full rounded-xl" />
      {Array.from({ length: 5 }).map((_, i) => (
        <Skeleton key={i} className="h-16 w-full rounded-xl" />
      ))}
    </div>
  )
}
