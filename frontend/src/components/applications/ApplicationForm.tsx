'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectItem } from '@/components/ui/select'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useCreateApplication } from '@/hooks/useApplications'
import { useAuth } from '@/lib/auth'
import { authApi } from '@/lib/api'
import { CustomerProfile } from '@/types'
import { AlertTriangle, UserCircle } from 'lucide-react'

const STEP_LABELS = ['Personal', 'Employment & Income', 'Expenses & Debts', 'Loan Details', 'Review & Submit']

const formSchema = z.object({
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

type FormData = z.infer<typeof formSchema>

interface ApplicationFormProps {
  onSuccessPath?: string
}

const FIELD_LABELS: Record<string, string> = {
  date_of_birth: 'Date of Birth',
  phone: 'Phone Number',
  address_line_1: 'Street Address',
  suburb: 'Suburb',
  state: 'State',
  postcode: 'Postcode',
  residency_status: 'Residency Status',
  primary_id_type: 'Primary ID Type',
  primary_id_number: 'Primary ID Number',
}

export function ApplicationForm({ onSuccessPath }: ApplicationFormProps = {}) {
  const [step, setStep] = useState(1)
  const totalSteps = STEP_LABELS.length
  const router = useRouter()
  const { user } = useAuth()
  const createApplication = useCreateApplication()
  const isCustomer = user?.role === 'customer'

  const DRAFT_KEY = 'loan_application_draft'

  const getSavedDraft = useCallback((): Partial<FormData> | null => {
    try {
      const saved = localStorage.getItem(DRAFT_KEY)
      if (saved) return JSON.parse(saved)
    } catch { /* ignore parse errors */ }
    return null
  }, [])

  const savedDraft = useRef(getSavedDraft())

  const {
    register,
    handleSubmit,
    trigger,
    watch,
    formState: { errors },
  } = useForm<FormData>({
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

  // Block customers with incomplete profiles
  if (isCustomer && profileLoading) {
    return (
      <div className="max-w-2xl mx-auto space-y-6">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (isCustomer && profile && !profile.is_profile_complete) {
    const missing = profile.missing_profile_fields || []
    return (
      <div className="max-w-2xl mx-auto">
        <Card className="border-amber-200 bg-amber-50/50">
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-amber-100">
                <AlertTriangle className="h-6 w-6 text-amber-600" />
              </div>
              <div>
                <CardTitle className="text-lg">Complete Your Profile First</CardTitle>
                <CardDescription className="text-amber-800">
                  Under the National Consumer Credit Protection Act 2009 (NCCP), we need your personal details before processing a loan application.
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-sm font-medium text-amber-900 mb-2">The following details are missing:</p>
              <ul className="grid grid-cols-2 gap-2">
                {missing.map((field) => (
                  <li key={field} className="flex items-center gap-2 text-sm text-amber-800">
                    <div className="h-1.5 w-1.5 rounded-full bg-amber-500 shrink-0" />
                    {FIELD_LABELS[field] || field.replace(/_/g, ' ')}
                  </li>
                ))}
              </ul>
            </div>
            <div className="flex gap-3 pt-2">
              <Link href="/apply/profile">
                <Button>
                  <UserCircle className="mr-2 h-4 w-4" />
                  Go to My Profile
                </Button>
              </Link>
            </div>
          </CardContent>
        </Card>
        <div className="flex justify-end mt-4">
          <Link href="/apply">
            <Button variant="outline">
              Finished
            </Button>
          </Link>
        </div>
      </div>
    )
  }

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

  const nextStep = async () => {
    let fieldsToValidate: (keyof FormData)[] = []
    if (step === 1) fieldsToValidate = ['applicant_type', 'number_of_dependants', 'home_ownership']
    if (step === 2) fieldsToValidate = ['annual_income', 'credit_score', 'employment_length', 'employment_type']
    if (step === 3) fieldsToValidate = ['debt_to_income', 'existing_credit_card_limit']
    if (step === 4) fieldsToValidate = ['loan_amount', 'loan_term_months', 'purpose']

    const valid = fieldsToValidate.length === 0 || await trigger(fieldsToValidate)
    if (valid) setStep(step + 1)
  }

  const submitApplication = () => {
    if (submittingRef.current || createApplication.isPending) return
    handleSubmit(onSubmit)()
  }

  const formatAUD = (value: number | undefined | null) => {
    if (value == null || isNaN(value)) return '—'
    return `A$${Number(value).toLocaleString('en-AU')}`
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Step indicator */}
      <div className="flex items-center justify-center gap-1 mb-8">
        {STEP_LABELS.map((label, i) => {
          const s = i + 1
          return (
            <div key={s} className="flex items-center">
              <div className="flex flex-col items-center">
                <div className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-medium transition-colors ${
                  s <= step ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                }`}>
                  {s}
                </div>
                <span className="text-[10px] text-muted-foreground mt-1 hidden sm:block">{label}</span>
              </div>
              {s < totalSteps && <div className={`h-0.5 w-6 sm:w-10 mx-1 ${s < step ? 'bg-primary' : 'bg-muted'}`} />}
            </div>
          )
        })}
      </div>

      {/* Step 1: Personal Information */}
      {step === 1 && (
        <Card>
          <CardHeader>
            <CardTitle>Personal Information</CardTitle>
            <CardDescription>Your household details affect HEM living expense benchmarks used in serviceability assessment.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>First Name</Label>
                <Input value={user?.first_name || ''} disabled />
              </div>
              <div>
                <Label>Last Name</Label>
                <Input value={user?.last_name || ''} disabled />
              </div>
            </div>
            <div>
              <Label>Email</Label>
              <Input value={user?.email || ''} disabled />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="applicant_type">Applicant Type</Label>
                <Select id="applicant_type" {...register('applicant_type')}>
                  <SelectItem value="single">Single Applicant</SelectItem>
                  <SelectItem value="couple">Joint Applicants (Couple)</SelectItem>
                </Select>
                {errors.applicant_type && <p className="text-sm text-destructive mt-1">{errors.applicant_type.message}</p>}
              </div>
              <div>
                <Label htmlFor="number_of_dependants">Number of Dependants</Label>
                <Input id="number_of_dependants" type="number" min={0} max={10} {...register('number_of_dependants')} />
                {errors.number_of_dependants && <p className="text-sm text-destructive mt-1">{errors.number_of_dependants.message}</p>}
              </div>
            </div>
            <div>
              <Label htmlFor="home_ownership">Current Living Situation</Label>
              <Select id="home_ownership" {...register('home_ownership')}>
                <SelectItem value="own">Own Outright</SelectItem>
                <SelectItem value="mortgage">Own with Mortgage</SelectItem>
                <SelectItem value="rent">Renting</SelectItem>
              </Select>
              {errors.home_ownership && <p className="text-sm text-destructive mt-1">{errors.home_ownership.message}</p>}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 2: Employment & Income */}
      {step === 2 && (
        <Card>
          <CardHeader>
            <CardTitle>Employment &amp; Income</CardTitle>
            <CardDescription>Income shading applies based on employment type — casual and self-employed income is assessed at 80% and 75% respectively under Big 4 bank criteria.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="employment_type">Employment Type</Label>
                <Select id="employment_type" {...register('employment_type')}>
                  <SelectItem value="payg_permanent">PAYG Full-Time/Permanent</SelectItem>
                  <SelectItem value="payg_casual">PAYG Casual</SelectItem>
                  <SelectItem value="self_employed">Self-Employed (ABN)</SelectItem>
                  <SelectItem value="contract">Fixed-Term Contract</SelectItem>
                </Select>
                {errors.employment_type && <p className="text-sm text-destructive mt-1">{errors.employment_type.message}</p>}
              </div>
              <div>
                <Label htmlFor="employment_length">Time in Current Role (years)</Label>
                <Input id="employment_length" type="number" min={0} aria-describedby="employment_length_help" {...register('employment_length')} />
                {errors.employment_length && <p className="text-sm text-destructive mt-1">{errors.employment_length.message}</p>}
                <p id="employment_length_help" className="text-xs text-muted-foreground mt-1">Self-employed applicants typically need 2+ years of ABN history.</p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="annual_income">Gross Annual Income (A$)</Label>
                <Input id="annual_income" type="number" aria-describedby="annual_income_help" {...register('annual_income')} placeholder="Before tax" />
                {errors.annual_income && <p className="text-sm text-destructive mt-1">{errors.annual_income.message}</p>}
                <p id="annual_income_help" className="text-xs text-muted-foreground mt-1">Include base salary, regular overtime, and allowances.</p>
              </div>
              <div>
                <Label htmlFor="credit_score">Equifax Credit Score (0–1200)</Label>
                <Input id="credit_score" type="number" min={0} max={1200} aria-describedby="credit_score_help" {...register('credit_score')} placeholder="Check via Equifax or credit savvy" />
                {errors.credit_score && <p className="text-sm text-destructive mt-1">{errors.credit_score.message}</p>}
                <p id="credit_score_help" className="text-xs text-muted-foreground mt-1">Australian average is ~800. Big 4 banks typically require 650+.</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 3: Expenses & Existing Debts */}
      {step === 3 && (
        <Card>
          <CardHeader>
            <CardTitle>Expenses &amp; Existing Debts</CardTitle>
            <CardDescription>Under APRA responsible lending guidelines, banks compare your declared expenses against the Household Expenditure Measure (HEM) benchmark and use the higher of the two.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Label htmlFor="monthly_expenses">Monthly Living Expenses (A$)</Label>
              <Input id="monthly_expenses" type="number" step="0.01" min={0} aria-describedby="monthly_expenses_help" {...register('monthly_expenses')} placeholder="Rent, groceries, transport, insurance, utilities, etc." />
              {errors.monthly_expenses && <p className="text-sm text-destructive mt-1">{errors.monthly_expenses.message}</p>}
              <p id="monthly_expenses_help" className="text-xs text-muted-foreground mt-1">If left blank, the HEM benchmark for your household type will be used. Include rent/board if applicable.</p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="existing_credit_card_limit">Total Credit Card Limits (A$)</Label>
                <Input id="existing_credit_card_limit" type="number" step="0.01" min={0} aria-describedby="credit_card_limit_help" {...register('existing_credit_card_limit')} placeholder="Combined across all cards" />
                {errors.existing_credit_card_limit && <p className="text-sm text-destructive mt-1">{errors.existing_credit_card_limit.message}</p>}
                <p id="credit_card_limit_help" className="text-xs text-muted-foreground mt-1">Banks assess 3% of your total limit as a monthly commitment, even if the balance is $0.</p>
              </div>
              <div>
                <Label htmlFor="debt_to_income">Debt-to-Income Ratio</Label>
                <Input id="debt_to_income" type="number" step="0.1" min={0} max={15} aria-describedby="dti_help" {...register('debt_to_income')} placeholder="e.g. 4.5" />
                {errors.debt_to_income && <p className="text-sm text-destructive mt-1">{errors.debt_to_income.message}</p>}
                <p id="dti_help" className="text-xs text-muted-foreground mt-1">Total existing debt divided by annual income. APRA caps this at 6x for most lenders.</p>
              </div>
            </div>
            <div className="rounded-lg bg-muted/50 p-3">
              <p className="text-xs text-muted-foreground">
                Include all existing debts: personal loans, car loans, HECS/HELP, buy-now-pay-later, and any other regular financial commitments. Credit card limits count even if unused.
              </p>
            </div>
            <div className="space-y-3 pt-2">
              <p className="text-sm font-medium">Declarations</p>
              <div className="flex items-start gap-2">
                <input
                  type="checkbox"
                  id="has_hecs"
                  className="h-4 w-4 rounded border-input mt-0.5"
                  aria-describedby="has_hecs_help"
                  {...register('has_hecs')}
                />
                <div>
                  <Label htmlFor="has_hecs">I have a HECS/HELP debt</Label>
                  <p id="has_hecs_help" className="text-xs text-muted-foreground">ATO compulsory repayment applies when your income exceeds the threshold (currently ~$54k). Lenders factor the repayment into serviceability.</p>
                </div>
              </div>
              <div className="flex items-start gap-2">
                <input
                  type="checkbox"
                  id="has_bankruptcy"
                  className="h-4 w-4 rounded border-input mt-0.5"
                  aria-describedby="has_bankruptcy_help"
                  {...register('has_bankruptcy')}
                />
                <div>
                  <Label htmlFor="has_bankruptcy">I have been declared bankrupt or discharged from bankruptcy within the last 7 years</Label>
                  <p id="has_bankruptcy_help" className="text-xs text-muted-foreground">Bankruptcy remains on your credit file for 5 years from discharge. Most lenders require at least 2 years post-discharge.</p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 4: Loan Details */}
      {step === 4 && (
        <Card>
          <CardHeader>
            <CardTitle>Loan Details</CardTitle>
            <CardDescription>Serviceability is assessed at the current rate plus a 3% APRA buffer to ensure you can manage repayments if rates rise.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="loan_amount">Loan Amount (A$)</Label>
                <Input id="loan_amount" type="number" {...register('loan_amount')} />
                {errors.loan_amount && <p className="text-sm text-destructive mt-1">{errors.loan_amount.message}</p>}
              </div>
              <div>
                <Label htmlFor="loan_term_months">Loan Term (months)</Label>
                <Select id="loan_term_months" {...register('loan_term_months')}>
                  <SelectItem value="12">12 months (1 year)</SelectItem>
                  <SelectItem value="24">24 months (2 years)</SelectItem>
                  <SelectItem value="36">36 months (3 years)</SelectItem>
                  <SelectItem value="60">60 months (5 years)</SelectItem>
                  <SelectItem value="84">84 months (7 years)</SelectItem>
                  <SelectItem value="240">240 months (20 years)</SelectItem>
                  <SelectItem value="300">300 months (25 years)</SelectItem>
                  <SelectItem value="360">360 months (30 years)</SelectItem>
                </Select>
                {errors.loan_term_months && <p className="text-sm text-destructive mt-1">{errors.loan_term_months.message}</p>}
              </div>
            </div>
            <div>
              <Label htmlFor="purpose">Loan Purpose</Label>
              <Select id="purpose" {...register('purpose')}>
                <SelectItem value="home">Home Purchase / Refinance</SelectItem>
                <SelectItem value="auto">Vehicle Loan</SelectItem>
                <SelectItem value="education">Education (non-HECS)</SelectItem>
                <SelectItem value="personal">Personal Loan</SelectItem>
                <SelectItem value="business">Business Loan</SelectItem>
              </Select>
              {errors.purpose && <p className="text-sm text-destructive mt-1">{errors.purpose.message}</p>}
            </div>
            {purpose === 'home' && (
              <div className="space-y-4 rounded-lg border p-4">
                <p className="text-sm font-medium">Home Loan Details</p>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="property_value">Property Value (A$)</Label>
                    <Input id="property_value" type="number" aria-describedby="property_value_help" {...register('property_value')} placeholder="Estimated or contract price" />
                    {errors.property_value && <p className="text-sm text-destructive mt-1">{errors.property_value.message}</p>}
                    <p id="property_value_help" className="text-xs text-muted-foreground mt-1">Used to calculate your LVR (Loan-to-Value Ratio).</p>
                  </div>
                  <div>
                    <Label htmlFor="deposit_amount">Deposit / Genuine Savings (A$)</Label>
                    <Input id="deposit_amount" type="number" aria-describedby="deposit_amount_help" {...register('deposit_amount')} placeholder="Held for 3+ months" />
                    {errors.deposit_amount && <p className="text-sm text-destructive mt-1">{errors.deposit_amount.message}</p>}
                    <p id="deposit_amount_help" className="text-xs text-muted-foreground mt-1">Most lenders require 5% genuine savings for LVR above 80%.</p>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">LVR above 80% will require Lenders Mortgage Insurance (LMI). LVR above 95% is generally not accepted.</p>
              </div>
            )}
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="has_cosigner"
                className="h-4 w-4 rounded border-input"
                {...register('has_cosigner')}
              />
              <Label htmlFor="has_cosigner">Applying with a guarantor or co-borrower</Label>
            </div>
            <div>
              <Label htmlFor="notes">Additional Notes (optional)</Label>
              <Input id="notes" {...register('notes')} placeholder="Any additional information relevant to your application..." />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 5: Review & Submit */}
      {step === 5 && (
        <Card>
          <CardHeader>
            <CardTitle>Review &amp; Submit</CardTitle>
            <CardDescription>Please review your details below. Your application will be assessed using Australian lending standards including the APRA serviceability buffer (+3%), HEM living expense benchmarks, LVR thresholds, and DTI caps.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5 text-sm">
            {/* Personal */}
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Personal</h4>
              <div className="grid grid-cols-2 gap-x-8 gap-y-1.5">
                <div className="text-muted-foreground">Name</div>
                <div>{user?.first_name} {user?.last_name}</div>
                <div className="text-muted-foreground">Applicant Type</div>
                <div className="capitalize">{watch('applicant_type')} ({watch('number_of_dependants')} dependants)</div>
                <div className="text-muted-foreground">Living Situation</div>
                <div className="capitalize">{watch('home_ownership')}</div>
              </div>
            </div>
            <hr />

            {/* Employment & Income */}
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Employment &amp; Income</h4>
              <div className="grid grid-cols-2 gap-x-8 gap-y-1.5">
                <div className="text-muted-foreground">Employment Type</div>
                <div>{watch('employment_type')?.replace(/_/g, ' ').replace(/payg/i, 'PAYG')}</div>
                <div className="text-muted-foreground">Time in Current Role</div>
                <div>{watch('employment_length')} years</div>
                <div className="text-muted-foreground">Gross Annual Income</div>
                <div>{formatAUD(watch('annual_income'))}</div>
                <div className="text-muted-foreground">Equifax Score</div>
                <div>{watch('credit_score') || '—'}</div>
              </div>
            </div>
            <hr />

            {/* Expenses & Debts */}
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Expenses &amp; Debts</h4>
              <div className="grid grid-cols-2 gap-x-8 gap-y-1.5">
                <div className="text-muted-foreground">Monthly Living Expenses</div>
                <div>{watch('monthly_expenses') ? formatAUD(watch('monthly_expenses')) : 'HEM benchmark'}</div>
                <div className="text-muted-foreground">Total Credit Card Limits</div>
                <div>{formatAUD(watch('existing_credit_card_limit'))}</div>
                <div className="text-muted-foreground">DTI Ratio</div>
                <div>{watch('debt_to_income')}x</div>
                <div className="text-muted-foreground">HECS/HELP Debt</div>
                <div>{watch('has_hecs') ? 'Yes' : 'No'}</div>
                <div className="text-muted-foreground">Bankruptcy History</div>
                <div>{watch('has_bankruptcy') ? 'Yes' : 'No'}</div>
              </div>
            </div>
            <hr />

            {/* Loan Details */}
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Loan Details</h4>
              <div className="grid grid-cols-2 gap-x-8 gap-y-1.5">
                <div className="text-muted-foreground">Loan Amount</div>
                <div className="font-semibold">{formatAUD(watch('loan_amount'))}</div>
                <div className="text-muted-foreground">Loan Term</div>
                <div>{watch('loan_term_months')} months</div>
                <div className="text-muted-foreground">Purpose</div>
                <div className="capitalize">{watch('purpose')}</div>
                {purpose === 'home' && (
                  <>
                    <div className="text-muted-foreground">Property Value</div>
                    <div>{formatAUD(watch('property_value'))}</div>
                    <div className="text-muted-foreground">Deposit</div>
                    <div>{formatAUD(watch('deposit_amount'))}</div>
                    <div className="text-muted-foreground">Estimated LVR</div>
                    <div>
                      {watch('property_value') && Number(watch('property_value')) > 0
                        ? `${((Number(watch('loan_amount')) / Number(watch('property_value'))) * 100).toFixed(1)}%`
                        : '—'}
                    </div>
                  </>
                )}
                <div className="text-muted-foreground">Guarantor / Co-borrower</div>
                <div>{watch('has_cosigner') ? 'Yes' : 'No'}</div>
              </div>
            </div>

            {watch('notes') && (
              <>
                <hr />
                <div>
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Notes</h4>
                  <p className="text-muted-foreground">{watch('notes')}</p>
                </div>
              </>
            )}

            <div className="rounded-lg bg-blue-50 border border-blue-200 p-3 mt-4">
              <p className="text-xs text-blue-800">
                By submitting this application, you consent to AussieLoanAI conducting a credit check via Equifax and assessing your application under the National Consumer Credit Protection Act 2009 and APRA prudential standards.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Navigation */}
      <div className="flex justify-between">
        <Button
          type="button"
          variant="outline"
          onClick={() => setStep(step - 1)}
          disabled={step === 1}
        >
          Previous
        </Button>
        {step < totalSteps ? (
          <Button type="button" onClick={nextStep}>
            Next
          </Button>
        ) : (
          <Button type="button" onClick={submitApplication} disabled={createApplication.isPending}>
            {createApplication.isPending ? 'Submitting...' : 'Submit Application'}
          </Button>
        )}
      </div>

      {createApplication.isError && (
        <p className="text-sm text-destructive text-center">
          Failed to submit application. Please try again.
        </p>
      )}
    </div>
  )
}
