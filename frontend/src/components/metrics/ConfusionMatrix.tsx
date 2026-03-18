'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface ConfusionMatrixProps {
  matrix: {
    tp?: number; fp?: number; tn?: number; fn?: number;
    true_positives?: number; false_positives?: number; true_negatives?: number; false_negatives?: number;
  }
}

export function ConfusionMatrix({ matrix: raw }: ConfusionMatrixProps) {
  const matrix = {
    tp: raw.tp ?? raw.true_positives ?? 0,
    fp: raw.fp ?? raw.false_positives ?? 0,
    tn: raw.tn ?? raw.true_negatives ?? 0,
    fn: raw.fn ?? raw.false_negatives ?? 0,
  }
  const total = matrix.tp + matrix.fp + matrix.tn + matrix.fn
  const maxVal = Math.max(matrix.tp, matrix.fp, matrix.tn, matrix.fn)

  function getIntensity(value: number): string {
    const ratio = maxVal > 0 ? value / maxVal : 0
    if (ratio > 0.75) return 'bg-blue-600 text-white'
    if (ratio > 0.5) return 'bg-blue-400 text-white'
    if (ratio > 0.25) return 'bg-blue-200 text-blue-900'
    return 'bg-blue-50 text-blue-900'
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Confusion Matrix</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          <div className="text-center text-sm font-medium text-muted-foreground mb-2">
            Predicted
          </div>
          <div className="flex items-center justify-center gap-2">
            <div className="w-20" />
            <div className="w-24 text-center text-xs font-medium text-muted-foreground">Positive</div>
            <div className="w-24 text-center text-xs font-medium text-muted-foreground">Negative</div>
          </div>
          <div className="flex items-center justify-center gap-2">
            <div className="w-20 text-right text-xs font-medium text-muted-foreground pr-2">
              Actual<br/>Positive
            </div>
            <div className={`flex h-24 w-24 items-center justify-center rounded-md text-lg font-bold ${getIntensity(matrix.tp)}`}>
              {matrix.tp}
              <span className="text-xs ml-1 opacity-75">TP</span>
            </div>
            <div className={`flex h-24 w-24 items-center justify-center rounded-md text-lg font-bold ${getIntensity(matrix.fn)}`}>
              {matrix.fn}
              <span className="text-xs ml-1 opacity-75">FN</span>
            </div>
          </div>
          <div className="flex items-center justify-center gap-2">
            <div className="w-20 text-right text-xs font-medium text-muted-foreground pr-2">
              Actual<br/>Negative
            </div>
            <div className={`flex h-24 w-24 items-center justify-center rounded-md text-lg font-bold ${getIntensity(matrix.fp)}`}>
              {matrix.fp}
              <span className="text-xs ml-1 opacity-75">FP</span>
            </div>
            <div className={`flex h-24 w-24 items-center justify-center rounded-md text-lg font-bold ${getIntensity(matrix.tn)}`}>
              {matrix.tn}
              <span className="text-xs ml-1 opacity-75">TN</span>
            </div>
          </div>
          <p className="text-center text-xs text-muted-foreground mt-2">
            Total: {total} samples
          </p>
        </div>
      </CardContent>
    </Card>
  )
}
