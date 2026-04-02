'use client'

import { useState } from 'react'
import { GuardrailCheck } from '@/types'
import { CheckCircle, XCircle, ChevronDown, ChevronRight, Shield, ShieldCheck, ShieldAlert } from 'lucide-react'

interface GuardrailLogDisplayProps {
  checks: GuardrailCheck[]
}

function CheckRow({ check, isExpanded, onToggle }: { check: GuardrailCheck; isExpanded: boolean; onToggle: () => void }) {
  return (
    <div className="rounded-md border">
      <button
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/50"
        onClick={onToggle}
      >
        {check.passed ? (
          <CheckCircle className="h-4 w-4 text-green-600 flex-shrink-0" />
        ) : (
          <XCircle className="h-4 w-4 text-red-600 flex-shrink-0" />
        )}
        <span className="flex-1 font-medium">{check.check_name}</span>
        {isExpanded ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
      </button>
      {isExpanded && (
        <div className="border-t px-3 py-2">
          <p className="text-sm text-muted-foreground">{check.details}</p>
        </div>
      )}
    </div>
  )
}

export function GuardrailLogDisplay({ checks }: GuardrailLogDisplayProps) {
  const [expandedNames, setExpandedNames] = useState<Set<string>>(new Set())

  const toggleExpand = (name: string) => {
    setExpandedNames((prev) => {
      const next = new Set(prev)
      if (next.has(name)) {
        next.delete(name)
      } else {
        next.add(name)
      }
      return next
    })
  }

  const totalChecks = checks.length
  const passedChecks = checks.filter((c) => c.passed).length
  const failedChecks = totalChecks - passedChecks
  const allPassed = failedChecks === 0
  const qualityScore = checks[0]?.quality_score ?? null

  return (
    <div className="space-y-3">
      {/* Summary header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield className="h-5 w-5 text-muted-foreground" />
          <h4 className="text-sm font-semibold">Compliance &amp; Guardrail Checks</h4>
        </div>
        <div className="flex items-center gap-3">
          {qualityScore !== null && (
            <span className={`text-xs font-mono px-2 py-0.5 rounded ${
              qualityScore >= 90 ? 'bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-400' :
              qualityScore >= 70 ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-400' :
              'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-400'
            }`}>
              {qualityScore}/100
            </span>
          )}
          <span className={`flex items-center gap-1 text-xs font-medium ${allPassed ? 'text-green-700 dark:text-green-400' : 'text-red-700 dark:text-red-400'}`}>
            {allPassed ? (
              <><ShieldCheck className="h-3.5 w-3.5" />{passedChecks}/{totalChecks} passed</>
            ) : (
              <><ShieldAlert className="h-3.5 w-3.5" />{passedChecks}/{totalChecks} passed</>
            )}
          </span>
        </div>
      </div>

      {/* All checks in a compact grid */}
      <div className="grid gap-1.5 sm:grid-cols-2">
        {checks.map((check, index) => (
          <CheckRow
            key={`${check.check_name}-${index}`}
            check={check}
            isExpanded={expandedNames.has(check.check_name)}
            onToggle={() => toggleExpand(check.check_name)}
          />
        ))}
      </div>
    </div>
  )
}
