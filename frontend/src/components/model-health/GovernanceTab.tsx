'use client'

import type { ModelCard } from '@/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Shield, AlertTriangle, FileText } from 'lucide-react'

interface GovernanceTabProps {
  card: ModelCard | null | undefined
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(2)}%`
}

export function GovernanceTab({ card }: GovernanceTabProps) {
  if (!card) {
    return (
      <div className="flex h-64 items-center justify-center mt-4">
        <div className="text-center space-y-2">
          <FileText className="h-12 w-12 mx-auto text-muted-foreground" />
          <p className="text-muted-foreground">No governance data available</p>
          <p className="text-sm text-muted-foreground">Train a model to populate the model card.</p>
        </div>
      </div>
    )
  }

  const reg = card.regulatory_compliance || {}
  const regLabels: Record<string, string> = {
    apra_cpg_235: 'APRA CPG 235',
    nccp_act: 'NCCP Act',
    banking_code: 'Banking Code of Practice',
  }

  return (
    <div className="grid gap-6 md:grid-cols-2 mt-4">
      {/* Intended use */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-base">Intended Use</CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          <div className="divide-y divide-border">
            <KV label="Primary Use" value={card.intended_use.primary_use} />
            <KV label="Users" value={card.intended_use.users} />
            <KV label="Out of Scope" value={card.intended_use.out_of_scope} />
          </div>
        </CardContent>
      </Card>

      {/* Training data */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-base">Training Data</CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          <div className="divide-y divide-border">
            <KV label="Description" value={card.training_data.description} />
            <KV label="Dataset Size" value={card.training_data.size > 0 ? card.training_data.size.toLocaleString() : '—'} mono />
            <KV label="Features" value={card.training_data.features > 0 ? card.training_data.features.toLocaleString() : '—'} mono />
            {Object.entries(card.training_data.label_distribution).map(([label, ratio]) => (
              <KV key={label} label={`Class: ${label}`} value={fmtPct(ratio as number)} mono />
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Synthetic data advisory */}
      {card.synthetic_data_validation?.status === 'available' && (
        <Card className="border-amber-200/50 bg-gradient-to-r from-amber-50/30 to-orange-50/30 md:col-span-2">
          <CardContent className="flex items-start gap-3 py-4">
            <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-amber-800">Synthetic Data Advisory</p>
              <p className="text-sm text-amber-700 mt-1">{card.synthetic_data_validation.note}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Regulatory compliance */}
      <Card className="md:col-span-2">
        <CardHeader className="pb-4">
          <CardTitle className="text-base">Regulatory Compliance</CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          <div className="divide-y divide-border">
            {Object.entries(reg).map(([key, compliant]) => (
              <div key={key} className="grid grid-cols-2 gap-4 px-6 py-2.5 items-center">
                <span className="text-sm text-muted-foreground">{regLabels[key] || key}</span>
                <span className="text-right">
                  {compliant ? (
                    <Badge variant="success">
                      <Shield className="h-3 w-3 mr-1" />Compliant
                    </Badge>
                  ) : (
                    <Badge variant="destructive">Non-Compliant</Badge>
                  )}
                </span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Independent validation */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-base">Independent Validation</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Status:</span>
            <Badge variant={card.independent_validation.status === 'validated' ? 'success' : 'warning'}>
              {card.independent_validation.status === 'validated' ? 'Validated' : 'Not Validated'}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-3">{card.independent_validation.note || card.independent_validation.outcome || ''}</p>
        </CardContent>
      </Card>

      {/* Limitations */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-base">Known Limitations</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2">
            {card.limitations.map((lim) => (
              <li key={lim} className="flex items-start gap-2 text-sm">
                <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                <span>{lim}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}

function KV({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="grid grid-cols-2 gap-4 px-6 py-2.5">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={`text-sm text-right ${mono ? 'font-mono tabular-nums' : ''}`}>{value}</span>
    </div>
  )
}
