'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectItem } from '@/components/ui/select'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useCreateApplication } from '@/hooks/useApplications'
import { useAuth } from '@/lib/auth'

const formSchema = z.object({
  annual_income: z.coerce.number().min(1, 'Annual income is required'),
  credit_score: z.coerce.number().min(300).max(850, 'Credit score must be between 300 and 850'),
  loan_amount: z.coerce.number().min(1, 'Loan amount is required'),
  loan_term_months: z.coerce.number().min(1, 'Loan term is required'),
  debt_to_income: z.coerce.number().min(0).max(100, 'DTI must be between 0 and 100'),
  employment_length: z.coerce.number().min(0, 'Employment length is required'),
  purpose: z.enum(['home', 'auto', 'education', 'personal', 'business']),
  home_ownership: z.enum(['own', 'rent', 'mortgage']),
  has_cosigner: z.boolean(),
  notes: z.string().optional(),
})

type FormData = z.infer<typeof formSchema>

export function ApplicationForm() {
  const [step, setStep] = useState(1)
  const router = useRouter()
  const { user } = useAuth()
  const createApplication = useCreateApplication()

  const {
    register,
    handleSubmit,
    trigger,
    formState: { errors },
  } = useForm<FormData>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      purpose: 'personal',
      home_ownership: 'rent',
      has_cosigner: false,
      loan_term_months: 36,
    },
  })

  const onSubmit = async (data: FormData) => {
    try {
      const result = await createApplication.mutateAsync(data)
      router.push(`/dashboard/applications/${result.id}`)
    } catch (error) {
      console.error('Failed to create application:', error)
    }
  }

  const nextStep = async () => {
    let fieldsToValidate: (keyof FormData)[] = []
    if (step === 1) fieldsToValidate = []
    if (step === 2) fieldsToValidate = ['annual_income', 'credit_score', 'employment_length', 'debt_to_income']

    const valid = fieldsToValidate.length === 0 || await trigger(fieldsToValidate)
    if (valid) setStep(step + 1)
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-center gap-2 mb-8">
        {[1, 2, 3].map((s) => (
          <div key={s} className="flex items-center">
            <div className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-medium ${
              s <= step ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
            }`}>
              {s}
            </div>
            {s < 3 && <div className={`h-0.5 w-12 ${s < step ? 'bg-primary' : 'bg-muted'}`} />}
          </div>
        ))}
      </div>

      {step === 1 && (
        <Card>
          <CardHeader>
            <CardTitle>Personal Information</CardTitle>
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
            <p className="text-sm text-muted-foreground">
              Personal information is auto-filled from your profile.
            </p>
          </CardContent>
        </Card>
      )}

      {step === 2 && (
        <Card>
          <CardHeader>
            <CardTitle>Financial Information</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="annual_income">Annual Income ($)</Label>
                <Input id="annual_income" type="number" {...register('annual_income')} />
                {errors.annual_income && <p className="text-sm text-destructive mt-1">{errors.annual_income.message}</p>}
              </div>
              <div>
                <Label htmlFor="credit_score">Credit Score</Label>
                <Input id="credit_score" type="number" min={300} max={850} {...register('credit_score')} />
                {errors.credit_score && <p className="text-sm text-destructive mt-1">{errors.credit_score.message}</p>}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="employment_length">Employment Length (years)</Label>
                <Input id="employment_length" type="number" min={0} {...register('employment_length')} />
                {errors.employment_length && <p className="text-sm text-destructive mt-1">{errors.employment_length.message}</p>}
              </div>
              <div>
                <Label htmlFor="debt_to_income">Debt-to-Income Ratio (%)</Label>
                <Input id="debt_to_income" type="number" step="0.1" min={0} max={100} {...register('debt_to_income')} />
                {errors.debt_to_income && <p className="text-sm text-destructive mt-1">{errors.debt_to_income.message}</p>}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {step === 3 && (
        <Card>
          <CardHeader>
            <CardTitle>Loan Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="loan_amount">Loan Amount ($)</Label>
                <Input id="loan_amount" type="number" {...register('loan_amount')} />
                {errors.loan_amount && <p className="text-sm text-destructive mt-1">{errors.loan_amount.message}</p>}
              </div>
              <div>
                <Label htmlFor="loan_term_months">Loan Term (months)</Label>
                <Input id="loan_term_months" type="number" {...register('loan_term_months')} />
                {errors.loan_term_months && <p className="text-sm text-destructive mt-1">{errors.loan_term_months.message}</p>}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="purpose">Purpose</Label>
                <Select id="purpose" {...register('purpose')}>
                  <SelectItem value="home">Home</SelectItem>
                  <SelectItem value="auto">Auto</SelectItem>
                  <SelectItem value="education">Education</SelectItem>
                  <SelectItem value="personal">Personal</SelectItem>
                  <SelectItem value="business">Business</SelectItem>
                </Select>
                {errors.purpose && <p className="text-sm text-destructive mt-1">{errors.purpose.message}</p>}
              </div>
              <div>
                <Label htmlFor="home_ownership">Home Ownership</Label>
                <Select id="home_ownership" {...register('home_ownership')}>
                  <SelectItem value="own">Own</SelectItem>
                  <SelectItem value="rent">Rent</SelectItem>
                  <SelectItem value="mortgage">Mortgage</SelectItem>
                </Select>
                {errors.home_ownership && <p className="text-sm text-destructive mt-1">{errors.home_ownership.message}</p>}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="has_cosigner"
                className="h-4 w-4 rounded border-input"
                {...register('has_cosigner')}
              />
              <Label htmlFor="has_cosigner">Has Co-signer</Label>
            </div>
            <div>
              <Label htmlFor="notes">Notes (optional)</Label>
              <Input id="notes" {...register('notes')} placeholder="Additional information..." />
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex justify-between">
        <Button
          type="button"
          variant="outline"
          onClick={() => setStep(step - 1)}
          disabled={step === 1}
        >
          Previous
        </Button>
        {step < 3 ? (
          <Button type="button" onClick={nextStep}>
            Next
          </Button>
        ) : (
          <Button type="submit" disabled={createApplication.isPending}>
            {createApplication.isPending ? 'Submitting...' : 'Submit Application'}
          </Button>
        )}
      </div>

      {createApplication.isError && (
        <p className="text-sm text-destructive text-center">
          Failed to submit application. Please try again.
        </p>
      )}
    </form>
  )
}
