'use client'

import { useState, useRef, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useCreateApplication } from '@/hooks/useApplications'
import { useCustomerProfile } from '@/hooks/useCustomerProfile'
import { useAuth } from '@/lib/auth'
import { DRAFT_STORAGE_KEY } from '@/lib/clientState'
import { formatApiError } from '@/lib/api'
import { EMPLOYMENT_TYPES } from '@/lib/loanFieldOptions'
import type { CustomerProfile } from '@/types'

export const STEP_LABELS = ['Personal', 'Employment & Income', 'Expenses & Debts', 'Loan Details', 'Review & Submit']

const formSchema = z.object({
  // Step 1: Personal
  applicant_type: z.enum(['single', 'couple']),
  number_of_dependants: z.coerce.number().min(0).max(10),
  home_ownership: z.enum(['own', 'rent', 'mortgage']),

  // Step 2: Employment & Income
  annual_income: z.coerce.number().min(1, 'Gross annual income is required'),
  employment_type: z.enum(EMPLOYMENT_TYPES),
  // Decimal years are fine: the API stores whole completed years.
  employment_length: z.coerce.number().min(0, 'Employment length is required'),
  credit_score: z.coerce.number().min(0).max(1200, 'Equifax score must be between 0 and 1200'),

  // Step 3: Expenses & Debts
  monthly_expenses: z.coerce.number().min(0).optional().nullable(),
  existing_credit_card_limit: z.coerce.number().min(0),
  debt_to_income: z.coerce.number().min(0).max(15, 'DTI ratio must be between 0 and 15'),
  has_hecs: z.boolean().default(false),
  has_bankruptcy: z.boolean().default(false),

  // Step 4: Loan Details
  loan_amount: z.coerce.number().min(1, 'Loan amount is required'),
  loan_term_months: z.coerce.number().min(1, 'Loan term is required'),
  purpose: z.enum(['home', 'auto', 'education', 'personal', 'business']),
  property_value: z.coerce.number().min(0).optional().nullable(),
  deposit_amount: z.coerce.number().min(0).optional().nullable(),
  has_cosigner: z.boolean(),
  notes: z.string().optional(),
})

export type FormData = z.infer<typeof formSchema>

const DRAFT_KEY = DRAFT_STORAGE_KEY
/** Drafts expire after 24 hours — mirrors TTL pattern used in useMetrics.ts (15 min for training tasks). */
const DRAFT_TTL_MS = 24 * 60 * 60 * 1000

interface DraftEnvelope {
  savedAt: number
  /** Username that saved the draft; login drops drafts owned by anyone else. */
  owner?: string | null
  data: Partial<FormData>
}

function loadSavedDraft(): Partial<FormData> | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    if (!raw) return null
    const envelope: DraftEnvelope = JSON.parse(raw)
    // Expire drafts older than DRAFT_TTL_MS
    if (Date.now() - envelope.savedAt > DRAFT_TTL_MS) {
      localStorage.removeItem(DRAFT_KEY)
      return null
    }
    return envelope.data
  } catch (e) { console.warn('[useApplicationForm] Failed to parse draft from localStorage:', e) }
  return null
}

/** Fields validated before leaving each step; steps not listed have none. */
const STEP_FIELDS: Record<number, (keyof FormData)[]> = {
  1: ['applicant_type', 'number_of_dependants', 'home_ownership'],
  2: ['annual_income', 'credit_score', 'employment_length', 'employment_type'],
  3: ['debt_to_income', 'existing_credit_card_limit'],
  4: ['loan_amount', 'loan_term_months', 'purpose'],
}

const FIELD_NAMES: Record<string, string> = {
  annual_income: 'Gross annual income',
  credit_score: 'Credit score',
  employment_length: 'Time in current role',
  employment_type: 'Employment type',
  monthly_expenses: 'Monthly living expenses',
  existing_credit_card_limit: 'Credit card limits',
  debt_to_income: 'Debt-to-income ratio',
  loan_amount: 'Loan amount',
  loan_term_months: 'Loan term',
  purpose: 'Loan purpose',
  property_value: 'Property value',
  deposit_amount: 'Deposit',
  number_of_dependants: 'Number of dependants',
  notes: 'Notes',
}

export function describeSubmitError(error: unknown): string {
  return formatApiError(error, { fallback: 'Failed to submit application. Please try again.', labels: FIELD_NAMES })
}

const HOUSING_TO_OWNERSHIP: Record<string, FormData['home_ownership']> = {
  own_outright: 'own',
  mortgage: 'mortgage',
  renting: 'rent',
  boarding: 'rent',
  living_with_parents: 'rent',
}
/** Profile answers that map onto application fields, so the applicant does not type them twice. */
function profileDefaults(profile: CustomerProfile): Partial<FormData> {
  const out: Partial<FormData> = {}
  if (profile.gross_annual_income) out.annual_income = Number(profile.gross_annual_income)
  if (profile.years_in_current_role != null) out.employment_length = Number(profile.years_in_current_role)
  if ((EMPLOYMENT_TYPES as readonly string[]).includes(profile.employment_status)) {
    out.employment_type = profile.employment_status as FormData['employment_type']
  }
  if (HOUSING_TO_OWNERSHIP[profile.housing_situation]) out.home_ownership = HOUSING_TO_OWNERSHIP[profile.housing_situation]
  if (profile.number_of_dependants != null) out.number_of_dependants = profile.number_of_dependants
  if (profile.other_credit_card_limits) out.existing_credit_card_limit = Number(profile.other_credit_card_limits)
  return out
}

export function useApplicationForm(onSuccessPath?: string) {
  const [step, setStep] = useState(1)
  const totalSteps = STEP_LABELS.length
  const stepRef = useRef<HTMLDivElement>(null)
  const router = useRouter()
  const { user } = useAuth()
  const createApplication = useCreateApplication()
  const isCustomer = user?.role === 'customer'

  // Read once on mount; useForm only consumes defaultValues on the first render
  const [savedDraft] = useState(loadSavedDraft)

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema) as any,
    defaultValues: {
      applicant_type: 'single',
      number_of_dependants: 0,
      home_ownership: 'rent',
      employment_type: 'payg_permanent',
      employment_length: 0,
      credit_score: 0,
      annual_income: 0,
      monthly_expenses: null,
      existing_credit_card_limit: 0,
      debt_to_income: 0,
      purpose: 'personal',
      loan_term_months: 36,
      has_cosigner: false,
      has_hecs: false,
      has_bankruptcy: false,
      ...savedDraft,
    },
  })

  const { register, handleSubmit, trigger, watch, formState: { errors } } = form

  const draftOwnerRef = useRef<string | null>(user?.username ?? null)
  useEffect(() => {
    draftOwnerRef.current = user?.username ?? null
  }, [user?.username])

  // Persist form state to localStorage on every change
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null
    const subscription = watch((values) => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        try {
          const envelope: DraftEnvelope = {
            savedAt: Date.now(),
            owner: draftOwnerRef.current,
            data: values as Partial<FormData>,
          }
          localStorage.setItem(DRAFT_KEY, JSON.stringify(envelope))
        } catch (e) { console.warn('[useApplicationForm] Failed to save draft to localStorage:', e) }
      }, 500)
    })
    return () => {
      if (timer) clearTimeout(timer)
      subscription.unsubscribe()
    }
  }, [watch])

  const submittingRef = useRef(false)

  const { data: profile, isLoading: profileLoading } = useCustomerProfile({ enabled: isCustomer, staleTime: 0 })

  // Pre-fill from the profile once, without overwriting a saved draft or anything typed.
  const prefilledRef = useRef(false)
  useEffect(() => {
    if (!profile || prefilledRef.current) return
    prefilledRef.current = true
    for (const [key, value] of Object.entries(profileDefaults(profile)) as [keyof FormData, never][]) {
      // getFieldState reads without subscribing the form to dirty-state re-renders.
      if ((savedDraft && key in savedDraft) || form.getFieldState(key).isDirty) continue
      form.setValue(key, value)
    }
  }, [profile, savedDraft, form])

  const onSubmit = async (data: FormData) => {
    if (submittingRef.current) return
    submittingRef.current = true
    try {
      const result = await createApplication.mutateAsync(data)
      localStorage.removeItem(DRAFT_KEY)
      const basePath = onSuccessPath || '/dashboard/applications'
      router.push(`${basePath}/${result.id}`)
    } catch (error) {
      console.error('Failed to create application:', error)
    } finally {
      // Always reset the guard — catches both catch-path and any throw inside
      // router.push() after a successful mutation (e.g. navigation error).
      submittingRef.current = false
    }
  }

  const goNext = async () => {
    const fieldsToValidate = STEP_FIELDS[step] ?? []
    const valid = fieldsToValidate.length === 0 || await trigger(fieldsToValidate)
    if (valid) {
      setStep(step + 1)
      setTimeout(() => stepRef.current?.focus(), 0)
    }
  }

  const goPrev = () => {
    if (step > 1) {
      setStep(step - 1)
      setTimeout(() => stepRef.current?.focus(), 0)
    }
  }

  const submitApplication = () => {
    if (submittingRef.current || createApplication.isPending) return
    handleSubmit(onSubmit)()
  }

  return {
    form,
    register,
    errors,
    watch,
    step,
    stepRef,
    totalSteps,
    profile,
    profileLoading,
    isCustomer,
    user,
    onSubmit: submitApplication,
    goNext,
    goPrev,
    submitting: createApplication.isPending,
    submitError: createApplication.isError ? describeSubmitError(createApplication.error) : null,
  }
}
