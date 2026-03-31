import { Skeleton } from '@/components/ui/skeleton'

export default function ApplicationDetailLoading() {
  return (
    <div className="space-y-6">
      {/* Application header + financial details */}
      <div className="grid gap-6 md:grid-cols-2">
        <Skeleton className="h-48 rounded-xl" />
        <Skeleton className="h-48 rounded-xl" />
      </div>
      {/* Credit profile */}
      <Skeleton className="h-32 rounded-xl" />
      {/* Pipeline controls */}
      <Skeleton className="h-12 rounded-xl" />
      {/* Decision section */}
      <Skeleton className="h-64 rounded-xl" />
      {/* Email preview */}
      <Skeleton className="h-48 rounded-xl" />
    </div>
  )
}
