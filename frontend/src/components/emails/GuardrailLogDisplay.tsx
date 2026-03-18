'use client'

import { useState } from 'react'
import { GuardrailCheck } from '@/types'
import { CheckCircle, XCircle, ChevronDown, ChevronRight } from 'lucide-react'

interface GuardrailLogDisplayProps {
  checks: GuardrailCheck[]
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

  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium">Guardrail Checks</h4>
      <div className="space-y-1">
        {checks.map((check, index) => (
          <div key={`${check.check_name}-${index}`} className="rounded-md border">
            <button
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/50"
              onClick={() => toggleExpand(check.check_name)}
            >
              {check.passed ? (
                <CheckCircle className="h-4 w-4 text-green-600 flex-shrink-0" />
              ) : (
                <XCircle className="h-4 w-4 text-red-600 flex-shrink-0" />
              )}
              <span className="flex-1 font-medium">{check.check_name}</span>
              {expandedNames.has(check.check_name) ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </button>
            {expandedNames.has(check.check_name) && (
              <div className="border-t px-3 py-2">
                <p className="text-sm text-muted-foreground">{check.details}</p>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
