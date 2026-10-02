import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const AUD_FORMATTER = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD' })

export function formatCurrency(amount: number): string {
  return AUD_FORMATTER.format(amount)
}

/**
 * Format a money value that may arrive pre-masked. Customer-facing endpoints
 * replace amounts with a bracket string (e.g. "Under $50,000"); that string is
 * shown as-is, since formatting it as a number would render "$NaN".
 */
export function formatMaybeMasked(amount: number | string): string {
  return typeof amount === 'string' ? amount : formatCurrency(amount)
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

export function formatDate(date: string): string {
  return new Date(date).toLocaleDateString('en-AU', { year: 'numeric', month: 'short', day: 'numeric' })
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  processing: 'bg-blue-100 text-blue-800',
  approved: 'bg-green-100 text-green-800',
  denied: 'bg-red-100 text-red-800',
  review: 'bg-amber-100 text-amber-800',
  queue_failed: 'bg-orange-100 text-orange-800',
}

// Statuses whose raw value is not a readable label
const STATUS_LABELS: Record<string, string> = {
  queue_failed: 'PROCESSING DELAYED',
}

export function getStatusColor(status: string): string {
  return STATUS_COLORS[status] || 'bg-gray-100 text-gray-800'
}

/**
 * Returns the display status and colour for an application,
 * taking the ML decision into account when status is 'review'.
 */
export function getDisplayStatus(status: string, decision?: { decision: string } | null): { label: string; color: string } {
  const d = decision?.decision
  if (status === 'review' && (d === 'approved' || d === 'denied')) {
    return { label: d.toUpperCase(), color: STATUS_COLORS[d] }
  }
  return { label: STATUS_LABELS[status] ?? status.toUpperCase(), color: getStatusColor(status) }
}

/** Display names for the model algorithms the backend can train. */
export const ALGORITHM_LABELS: Record<string, string> = { rf: 'Random Forest', xgb: 'XGBoost' }

const PURPOSE_LABELS: Record<string, string> = {
  home: 'Home Purchase',
  home_improvement: 'Home Improvement',
  auto: 'Vehicle',
  personal: 'Personal',
  business: 'Business',
  education: 'Education',
}

/**
 * snake_case -> "Title Case": underscores become spaces and each word's first
 * letter is capitalised. Existing capitals are preserved, so codes like
 * "NSW"/"NT" stay intact ("payg casual" -> "Payg Casual").
 */
export function titleCase(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function formatPurpose(purpose: string | null | undefined): string {
  if (!purpose) return ''
  const key = purpose.toLowerCase()
  return PURPOSE_LABELS[key] || titleCase(key)
}

