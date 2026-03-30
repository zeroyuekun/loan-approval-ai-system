import { describe, it, expect } from 'vitest'
import { cn, formatCurrency, formatPercent, formatDate, getStatusColor, getDisplayStatus } from '@/lib/utils'

describe('cn', () => {
  it('merges class names', () => {
    expect(cn('px-2', 'py-1')).toBe('px-2 py-1')
  })

  it('resolves tailwind conflicts (last wins)', () => {
    const result = cn('px-2', 'px-4')
    expect(result).toBe('px-4')
  })

  it('handles conditional classes', () => {
    expect(cn('base', false && 'hidden', 'extra')).toBe('base extra')
  })

  it('handles undefined and null', () => {
    expect(cn('base', undefined, null)).toBe('base')
  })
})

describe('formatCurrency', () => {
  it('formats as AUD', () => {
    const result = formatCurrency(25000)
    expect(result).toContain('25,000')
    expect(result).toContain('$')
  })

  it('formats zero', () => {
    const result = formatCurrency(0)
    expect(result).toContain('0')
  })

  it('formats decimals', () => {
    const result = formatCurrency(1234.56)
    expect(result).toContain('1,234.56')
  })

  it('formats large amounts', () => {
    const result = formatCurrency(1500000)
    expect(result).toContain('1,500,000')
  })
})

describe('formatPercent', () => {
  it('formats decimal as percentage', () => {
    expect(formatPercent(0.875)).toBe('87.5%')
  })

  it('formats zero', () => {
    expect(formatPercent(0)).toBe('0.0%')
  })

  it('formats 1.0 as 100%', () => {
    expect(formatPercent(1)).toBe('100.0%')
  })

  it('formats small values', () => {
    expect(formatPercent(0.003)).toBe('0.3%')
  })
})

describe('formatDate', () => {
  it('formats ISO date to en-AU locale', () => {
    const result = formatDate('2026-03-27T10:00:00Z')
    expect(result).toContain('27')
    expect(result).toContain('Mar')
    expect(result).toContain('2026')
  })

  it('handles date-only strings', () => {
    const result = formatDate('2025-01-15')
    expect(result).toContain('15')
    expect(result).toContain('Jan')
    expect(result).toContain('2025')
  })
})

describe('getStatusColor', () => {
  it('returns yellow for pending', () => {
    expect(getStatusColor('pending')).toContain('yellow')
  })

  it('returns blue for processing', () => {
    expect(getStatusColor('processing')).toContain('blue')
  })

  it('returns green for approved', () => {
    expect(getStatusColor('approved')).toContain('green')
  })

  it('returns red for denied', () => {
    expect(getStatusColor('denied')).toContain('red')
  })

  it('returns amber for review', () => {
    expect(getStatusColor('review')).toContain('amber')
  })

  it('returns gray fallback for unknown status', () => {
    expect(getStatusColor('unknown')).toContain('gray')
  })
})

describe('getDisplayStatus', () => {
  it('returns APPROVED with green for review status + approved decision', () => {
    const result = getDisplayStatus('review', { decision: 'approved' })
    expect(result.label).toBe('APPROVED')
    expect(result.color).toContain('green')
  })

  it('returns DENIED with red for review status + denied decision', () => {
    const result = getDisplayStatus('review', { decision: 'denied' })
    expect(result.label).toBe('DENIED')
    expect(result.color).toContain('red')
  })

  it('returns REVIEW for review status with no decision', () => {
    const result = getDisplayStatus('review', null)
    expect(result.label).toBe('REVIEW')
    expect(result.color).toContain('amber')
  })

  it('returns REVIEW for review status with undefined decision', () => {
    const result = getDisplayStatus('review')
    expect(result.label).toBe('REVIEW')
  })

  it('returns uppercased status for non-review statuses', () => {
    const result = getDisplayStatus('pending')
    expect(result.label).toBe('PENDING')
    expect(result.color).toContain('yellow')
  })

  it('ignores decision for non-review statuses', () => {
    const result = getDisplayStatus('pending', { decision: 'approved' })
    expect(result.label).toBe('PENDING')
  })
})
