'use client'

import { useState } from 'react'

interface BiasScoreBadgeProps {
  score: number
  categories: string[]
}

function getColor(score: number): { bg: string; text: string; ring: string } {
  if (score <= 30) return { bg: 'bg-green-100', text: 'text-green-700', ring: 'ring-green-500' }
  if (score <= 60) return { bg: 'bg-yellow-100', text: 'text-yellow-700', ring: 'ring-yellow-500' }
  return { bg: 'bg-red-100', text: 'text-red-700', ring: 'ring-red-500' }
}

export function BiasScoreBadge({ score, categories }: BiasScoreBadgeProps) {
  const [showTooltip, setShowTooltip] = useState(false)
  const colors = getColor(score)

  return (
    <div className="relative inline-block">
      <div
        className={`flex h-14 w-14 cursor-pointer items-center justify-center rounded-full ${colors.bg} ring-2 ${colors.ring}`}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
      >
        <span className={`text-sm font-bold ${colors.text}`}>{score}</span>
      </div>

      {showTooltip && categories.length > 0 && (
        <div className="absolute left-1/2 top-full z-10 mt-2 -translate-x-1/2 rounded-md border bg-popover p-3 shadow-md">
          <p className="text-xs font-medium mb-1">Bias Categories:</p>
          <ul className="text-xs text-muted-foreground space-y-0.5">
            {categories.map((cat, i) => (
              <li key={i}>{cat}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
