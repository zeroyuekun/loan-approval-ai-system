import { Skeleton } from '@/components/ui/skeleton'

export default function ModelMetricsLoading() {
  return (
    <div className="space-y-6">
      {/* Model info bar */}
      <div className="flex items-center justify-between">
        <Skeleton className="h-8 w-48 rounded-xl" />
        <Skeleton className="h-10 w-56 rounded-xl" />
      </div>
      {/* Key metric cards */}
      <div className="grid gap-4 grid-cols-2 md:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-20 rounded-xl" />
        ))}
      </div>
      {/* Charts */}
      <div className="grid gap-6 md:grid-cols-2">
        <Skeleton className="h-64 rounded-xl" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
      {/* Feature importance */}
      <Skeleton className="h-64 rounded-xl" />
    </div>
  )
}
