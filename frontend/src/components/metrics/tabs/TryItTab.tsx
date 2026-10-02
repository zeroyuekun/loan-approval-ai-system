'use client'

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { mlApi } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectItem } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { AdhocScoreFields, AdhocScoreResult } from '@/types'
import {
  APPLICANT_TYPE_OPTIONS,
  AU_STATE_OPTIONS,
  EMPLOYMENT_TYPE_OPTIONS,
  FieldOption,
  HOME_OWNERSHIP_OPTIONS,
  LOAN_TERM_OPTIONS,
  PURPOSE_OPTIONS,
} from '@/lib/loanFieldOptions'
import { TryItResult } from './TryItResult'

// A plausible AU applicant so the tab has something sensible to score on
// first render, without the officer having to fill in every field.
const SAMPLE_APPLICANT: Record<string, string> = {
  annual_income: '95000',
  credit_score: '780',
  loan_amount: '450000',
  loan_term_months: '360',
  debt_to_income: '3.2',
  employment_length: '4',
  number_of_dependants: '0',
  // A home loan needs a property value (LVR); these keep the sample
  // consistent: LVR 75%, deposit below the property value.
  property_value: '600000',
  deposit_amount: '150000',
  monthly_expenses: '3000',
  purpose: 'home',
  home_ownership: 'mortgage',
  employment_type: 'payg_permanent',
  applicant_type: 'single',
  state: 'NSW',
}

// `homeOnly` fields are shown and sent only when the purpose is a home loan.
const NUMBER_FIELDS: Array<{ key: string; label: string; step?: string; homeOnly?: boolean }> = [
  { key: 'annual_income', label: 'Annual Income (A$)' },
  { key: 'credit_score', label: 'Credit Score (0-1200)' },
  { key: 'loan_amount', label: 'Loan Amount (A$)' },
  { key: 'debt_to_income', label: 'Debt-to-Income (x income)', step: '0.1' },
  { key: 'employment_length', label: 'Employment Length (years)' },
  { key: 'number_of_dependants', label: 'Number of Dependants' },
  { key: 'monthly_expenses', label: 'Monthly Expenses (A$)' },
  { key: 'property_value', label: 'Property Value (A$)', homeOnly: true },
  { key: 'deposit_amount', label: 'Deposit (A$)', homeOnly: true },
]

function visibleNumberFields(purpose: string) {
  return NUMBER_FIELDS.filter((f) => !f.homeOnly || purpose === 'home')
}

const SELECT_FIELDS: Array<{ key: string; label: string; options: FieldOption[] }> = [
  { key: 'purpose', label: 'Loan Purpose', options: PURPOSE_OPTIONS },
  { key: 'home_ownership', label: 'Home Ownership', options: HOME_OWNERSHIP_OPTIONS },
  { key: 'employment_type', label: 'Employment Type', options: EMPLOYMENT_TYPE_OPTIONS },
  { key: 'applicant_type', label: 'Applicant Type', options: APPLICANT_TYPE_OPTIONS },
  { key: 'state', label: 'State', options: AU_STATE_OPTIONS },
  { key: 'loan_term_months', label: 'Loan Term', options: LOAN_TERM_OPTIONS },
]

const KNOWN_FIELD_KEYS = new Set([...NUMBER_FIELDS, ...SELECT_FIELDS].map((f) => f.key))

/** Build the request body. An empty number input is left out (the backend
 * then reports it as required, or treats it as not supplied) rather than
 * sent as `Number('') === 0`, which would be scored as a real zero. */
function toPayload(form: Record<string, string>): AdhocScoreFields {
  const payload: Record<string, string | number> = {
    purpose: form.purpose,
    home_ownership: form.home_ownership,
    employment_type: form.employment_type,
    applicant_type: form.applicant_type,
    state: form.state,
    loan_term_months: Number(form.loan_term_months),
  }
  for (const f of visibleNumberFields(form.purpose)) {
    const raw = (form[f.key] ?? '').trim()
    if (raw !== '') payload[f.key] = Number(raw)
  }
  return payload as unknown as AdhocScoreFields
}

function badRequestData(error: unknown): Record<string, unknown> | null {
  const response = (error as { response?: { status?: number; data?: unknown } } | undefined)?.response
  if (response?.status !== 400 || typeof response.data !== 'object' || response.data === null) return null
  return response.data as Record<string, unknown>
}

/** DRF validation errors keyed by field name, e.g. `{"credit_score": [".."]}`. */
function fieldErrorsFrom(error: unknown): Record<string, string> | null {
  const data = badRequestData(error)
  if (!data) return null
  return Object.fromEntries(
    Object.entries(data)
      .filter(([key]) => key !== 'detail')
      .map(([key, value]) => [key, Array.isArray(value) ? value.join(' ') : String(value)]),
  )
}

/** A 400 `{"detail": "..."}`: the applicant's figures were rejected as a whole. */
function detailErrorFrom(error: unknown): string | null {
  const detail = badRequestData(error)?.detail
  return typeof detail === 'string' ? detail : null
}

/** The 503 "no active model" case, or any other unexpected failure. */
function serviceErrorFrom(error: unknown): string | null {
  const response = (error as { response?: { status?: number; data?: { detail?: string } } } | undefined)?.response
  if (response?.status === 503) return response.data?.detail || 'No active model'
  if (response?.status != null && response.status !== 400) return 'Failed to score applicant. Please try again.'
  if (error != null && response == null) return 'Failed to score applicant. Please try again.'
  return null
}

export function TryItTab() {
  const [form, setForm] = useState<Record<string, string>>(SAMPLE_APPLICANT)

  const mutation = useMutation<AdhocScoreResult, unknown, AdhocScoreFields>({
    mutationFn: async (fields) => (await mlApi.scoreApplicant(fields)).data,
  })

  const fieldErrors = fieldErrorsFrom(mutation.error)
  const serviceError = serviceErrorFrom(mutation.error) ?? detailErrorFrom(mutation.error)
  const otherFieldErrors = fieldErrors
    ? Object.entries(fieldErrors).filter(([key]) => !KNOWN_FIELD_KEYS.has(key))
    : []

  const handleChange = (key: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setForm((f) => ({ ...f, [key]: e.target.value }))
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    mutation.mutate(toPayload(form))
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Try it</CardTitle>
          <CardDescription>
            Score one applicant&apos;s facts against the active model. Nothing is saved — this is a quick
            what-if check, not a real application.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {otherFieldErrors.length > 0 && (
              <ul className="space-y-1 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                {otherFieldErrors.map(([field, message]) => (
                  <li key={field}>
                    <span className="font-medium">{field}:</span> {message}
                  </li>
                ))}
              </ul>
            )}
            {serviceError && (
              <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                {serviceError}
              </p>
            )}

            <div className="grid gap-4 md:grid-cols-3">
              {visibleNumberFields(form.purpose).map((f) => (
                <div key={f.key}>
                  <Label htmlFor={f.key}>{f.label}</Label>
                  <Input id={f.key} type="number" step={f.step} value={form[f.key]} onChange={handleChange(f.key)} />
                  {fieldErrors?.[f.key] && <p className="mt-1 text-sm text-destructive">{fieldErrors[f.key]}</p>}
                </div>
              ))}
              {SELECT_FIELDS.map((f) => (
                <div key={f.key}>
                  <Label htmlFor={f.key}>{f.label}</Label>
                  <Select id={f.key} value={form[f.key]} onChange={handleChange(f.key)}>
                    {f.options.map((o) => (
                      <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                    ))}
                  </Select>
                  {fieldErrors?.[f.key] && <p className="mt-1 text-sm text-destructive">{fieldErrors[f.key]}</p>}
                </div>
              ))}
            </div>

            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {mutation.isPending ? 'Scoring...' : 'Score Applicant'}
            </Button>
          </form>
        </CardContent>
      </Card>

      {mutation.isSuccess && mutation.data && <TryItResult result={mutation.data} />}
    </div>
  )
}
