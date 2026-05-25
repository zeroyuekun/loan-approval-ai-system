'use client'

import { useModelMetrics } from '@/hooks/useMetrics'
import { useDriftReports } from '@/hooks/useDriftReports'
import { useModelCard } from '@/hooks/useModelCard'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Skeleton } from '@/components/ui/skeleton'
import { ProductionStatusTab } from '@/components/model-health/ProductionStatusTab'
import { ModelDetailTab } from '@/components/model-health/ModelDetailTab'
import { GovernanceTab } from '@/components/model-health/GovernanceTab'
import { XCircle, Cpu } from 'lucide-react'

export default function ModelHealthPage() {
  const { data: metrics, isLoading: metricsLoading, isError: metricsError } = useModelMetrics()
  const { data: driftReports } = useDriftReports(6)
  const { data: card } = useModelCard()

  // Default tab honours url hash (#production / #model-detail / #governance)
  // so legacy bookmarks land on the right tab after redirect. The local
  // Tabs component is uncontrolled (defaultValue-only) so this is read
  // once at mount and then user-controlled internally.
  const initialTab = (() => {
    if (typeof window === 'undefined') return 'production'
    const hash = window.location.hash.replace('#', '')
    return ['production', 'model-detail', 'governance'].includes(hash) ? hash : 'production'
  })()

  if (metricsLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <div className="grid gap-6 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-64" />
          ))}
        </div>
      </div>
    )
  }

  if (metricsError) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-center space-y-2">
          <XCircle className="h-12 w-12 mx-auto text-red-400" />
          <p className="text-muted-foreground">Failed to load model health</p>
          <p className="text-sm text-muted-foreground">Check that the backend is running and try refreshing the page.</p>
        </div>
      </div>
    )
  }

  if (!metrics) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-center space-y-2">
          <Cpu className="h-12 w-12 mx-auto text-muted-foreground" />
          <p className="text-muted-foreground">No active model found</p>
          <p className="text-sm text-muted-foreground">Train a model to populate this page.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <Tabs defaultValue={initialTab}>
        <TabsList>
          <TabsTrigger value="production">Production Status</TabsTrigger>
          <TabsTrigger value="model-detail">Model Detail</TabsTrigger>
          <TabsTrigger value="governance">Governance</TabsTrigger>
        </TabsList>

        <TabsContent value="production">
          <ProductionStatusTab metrics={metrics} driftReports={driftReports ?? []} />
        </TabsContent>

        <TabsContent value="model-detail">
          <ModelDetailTab metrics={metrics} card={card} />
        </TabsContent>

        <TabsContent value="governance">
          <GovernanceTab card={card} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
