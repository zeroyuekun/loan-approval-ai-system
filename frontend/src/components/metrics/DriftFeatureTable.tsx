'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import { DriftReport } from '@/types'

interface DriftFeatureTableProps {
  report: DriftReport
}

export function DriftFeatureTable({ report }: DriftFeatureTableProps) {
  const features = report.psi_per_feature
  if (!features || Object.keys(features).length === 0) return null

  const sorted = Object.entries(features)
    .map(([name, value]) => ({ name, value: value as number }))
    .sort((a, b) => b.value - a.value)

  function getStatus(psi: number): { label: string; variant: 'success' | 'warning' | 'destructive' } {
    if (psi >= 0.25) return { label: 'Significant', variant: 'destructive' }
    if (psi >= 0.10) return { label: 'Moderate', variant: 'warning' }
    return { label: 'Stable', variant: 'success' }
  }

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">Per-Feature PSI</CardTitle>
      </CardHeader>
      <CardContent className="px-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Feature</TableHead>
              <TableHead className="text-right">PSI Value</TableHead>
              <TableHead className="text-right">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((f) => {
              const status = getStatus(f.value)
              return (
                <TableRow key={f.name}>
                  <TableCell className="font-medium">
                    {f.name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {f.value.toFixed(4)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Badge variant={status.variant}>{status.label}</Badge>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
