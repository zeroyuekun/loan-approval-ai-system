'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { titleCase } from '@/lib/utils'
import { normalizeConfusionMatrix } from '@/components/metrics/ConfusionMatrix'
import { fairnessStatus, type FairnessStatus } from '@/components/metrics/FairnessCard'
import type { ModelMetrics } from '@/types'

type Verdict = { label: string; className: string }

const GOOD = 'bg-emerald-100 text-emerald-800 hover:bg-emerald-100'
const FAIR = 'bg-amber-100 text-amber-800 hover:bg-amber-100'
const WEAK = 'bg-red-100 text-red-800 hover:bg-red-100'

// Conventional credit-scoring bands for AUC: 0.8+ strong, 0.7-0.8 acceptable.
function qualityVerdict(auc: number): Verdict {
  if (auc >= 0.8) return { label: 'Good', className: GOOD }
  if (auc >= 0.7) return { label: 'Fair', className: FAIR }
  return { label: 'Needs work', className: WEAK }
}

const STATUS: Record<FairnessStatus, { text: string; className: string }> = {
  pass: { text: 'Pass', className: 'font-medium text-emerald-700' },
  fail: { text: 'Fail', className: 'font-medium text-red-700' },
  unknown: { text: 'Not enough data', className: '' },
}

const n = (x: number) => x.toLocaleString('en-AU')
const strong = (text: string | number) => <span className="font-semibold text-foreground">{text}</span>

function SummaryCard({ title, badge, children }: { title: string; badge?: Verdict | null; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-base">{title}</CardTitle>
          {badge && <Badge className={badge.className}>{badge.label}</Badge>}
        </div>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">{children}</CardContent>
    </Card>
  )
}

export function ModelSummary({ metrics }: { metrics: ModelMetrics }) {
  const auc = metrics.auc_roc
  // Positive class = approved, so a false negative is a good borrower declined.
  const { tp, fp, tn, fn } = normalizeConfusionMatrix(metrics.confusion_matrix)
  const tested = tp + fp + tn + fn
  const fairness = Object.entries(metrics.fairness_metrics ?? {})
    .filter(([, v]) => v && typeof v === 'object' && 'groups' in v)
    .map(([name, v]) => ({ name: titleCase(name), status: fairnessStatus(v) }))
  const allPass = fairness.every((f) => f.status === 'pass')

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <SummaryCard title="Is the model accurate?" badge={auc != null ? qualityVerdict(auc) : null}>
        {auc == null ? (
          'No accuracy score recorded for this model.'
        ) : (
          <>Shown one borrower who repaid and one who did not, it ranks the safer one higher {strong(`${Math.round(auc * 100)}%`)} of the time.</>
        )}
      </SummaryCard>

      <SummaryCard title="What mistakes does it make?">
        {tested === 0 ? (
          'No test results recorded for this model.'
        ) : (
          <>
            <p>
              On {n(tested)} past applications held back for testing, it got {strong(`${Math.round(((tp + tn) / tested) * 100)}%`)} right.
            </p>
            <ul className="mt-2 space-y-1">
              <li>{strong(n(fn))} good borrowers wrongly declined</li>
              <li>{strong(n(fp))} risky borrowers wrongly approved</li>
            </ul>
          </>
        )}
      </SummaryCard>

      <SummaryCard
        title="Is it fair?"
        badge={fairness.length === 0 ? null : allPass ? { label: 'Passes', className: GOOD } : { label: 'Check', className: WEAK }}
      >
        {fairness.length === 0 ? (
          'No fairness check recorded for this model.'
        ) : (
          <>
            <p>Approval rates compared across groups (each group within 80% of the best-treated one):</p>
            <ul className="mt-2 space-y-1">
              {fairness.map((f) => (
                <li key={f.name} className="flex justify-between gap-2">
                  <span>{f.name}</span>
                  <span className={STATUS[f.status].className}>{STATUS[f.status].text}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </SummaryCard>
    </div>
  )
}
