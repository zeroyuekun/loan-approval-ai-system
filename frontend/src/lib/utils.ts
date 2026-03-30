import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD' }).format(amount)
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

export function formatDate(date: string): string {
  return new Date(date).toLocaleDateString('en-AU', { year: 'numeric', month: 'short', day: 'numeric' })
}

export function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    pending: 'bg-yellow-100 text-yellow-800',
    processing: 'bg-blue-100 text-blue-800',
    approved: 'bg-green-100 text-green-800',
    denied: 'bg-red-100 text-red-800',
    review: 'bg-amber-100 text-amber-800',
  }
  return colors[status] || 'bg-gray-100 text-gray-800'
}

/**
 * Returns the display status and colour for an application,
 * taking the ML decision into account when status is 'review'.
 */
export function getDisplayStatus(status: string, decision?: { decision: string } | null): { label: string; color: string } {
  if (status === 'review' && decision?.decision) {
    const d = decision.decision
    if (d === 'approved') return { label: 'APPROVED', color: 'bg-green-100 text-green-800' }
    if (d === 'denied') return { label: 'DENIED', color: 'bg-red-100 text-red-800' }
  }
  const label = status.toUpperCase()
  return { label, color: getStatusColor(status) }
}

