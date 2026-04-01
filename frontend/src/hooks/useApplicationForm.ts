'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useCreateApplication } from '@/hooks/useApplications'
import { useAuth } from '@/lib/auth'
import { authApi } from '@/lib/api'
import { CustomerProfile } from '@/types'

export const STEP_LABELS = ['Personal', 'Employment & Income', 'Expenses & Debts', 'Loan Details', 'Review & Submit']

export const formSchema = z.object({
  // Step 1: Personal
  applicant_type: z.enum(['single', 'couple']),
  number_of_dependants: z.coerce.number().min(0).max(10),
  home_ownership: z.enum(['own', 'rent', 'mortgage']),

  // Step 2: Employment & Income
  annual_income: z.coerce.number().min(1, 'Gross annual income is required'),
  employment_type: z.enum(['payg_permanent', 'payg_casual', 'self_employed', 'contract']),
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

const DRAFT_KEY = 'loan_application_draft'

export function useApplicationForm(onSuccessPath?: string) {
  const [step, setStep] = useState(1)
  const totalSteps = STEP_LABELS.length
  const stepRef = useRef<HTMLDivElement>(null)
  const router = useRouter()
  const { user } = useAuth()
  const createApplication = useCreateApplication()
  const isCustomer = user?.role === 'customer'

  const getSavedDraft = useCallback((): Partial<FormData> | null => {
    try {
      const saved = localStorage.getItem(DRAFT_KEY)
      if (saved) return JSON.parse(saved)
    } catch { /* ignore parse errors */ }
    return null
  }, [])

  const savedDraft = useRef(getSavedDraft())

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
      ...savedDraft.current,
    },
  })

  const { register, handleSubmit, trigger, watch, formState: { errors } } = form

  const purpose = watch('purpose')

  // Persist form state to localStorage on every change
  useEffect(() => {
    const subscription = watch((values) => {
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify(values))
      } catch { /* ignore quota errors */ }
    })
    return () => subscription.unsubscribe()
  }, [watch])

  const submittingRef = useRef(false)

  const { data: profile, isLoading: profileLoading } = useQuery<CustomerProfile>({
    queryKey: ['customerProfile'],
    queryFn: async () => {
      const { data } = await authApi.getCustomerProfile()
      return data
    },
    enabled: isCustomer,
    staleTime: 0,
  })

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
      submittingRef.current = false
    }
  }

  const goNext = async () => {
    let fieldsToValidate: (keyof FormData)[] = []
    if (step === 1) fieldsToValidate = ['applicant_type', 'number_of_dependants', 'home_ownership']
    if (step === 2) fieldsToValidate = ['annual_income', 'credit_score', 'employment_length', 'employment_type']
    if (step === 3) fieldsToValidate = ['debt_to_income', 'existing_credit_card_limit']
    if (step === 4) fieldsToValidate = ['loan_amount', 'loan_term_months', 'purpose']

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
    setStep,
    stepRef,
    totalSteps,
    purpose,
    profile,
    profileLoading,
    isCustomer,
    user,
    onSubmit: submitApplication,
    goNext,
    goPrev,
    submitting: createApplication.isPending,
    submitError: createApplication.isError,
  }
}
