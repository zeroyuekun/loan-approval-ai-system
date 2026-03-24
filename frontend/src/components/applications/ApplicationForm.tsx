'use client'

import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { AlertTriangle, UserCircle } from 'lucide-react'
import { useApplicationForm, STEP_LABELS } from '@/hooks/useApplicationForm'
import { PersonalStep } from './steps/PersonalStep'
import { EmploymentStep } from './steps/EmploymentStep'
import { ExpensesStep } from './steps/ExpensesStep'
import { LoanDetailsStep } from './steps/LoanDetailsStep'
import { ReviewStep } from './steps/ReviewStep'

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

interface ApplicationFormProps {
  onSuccessPath?: string
}

export function ApplicationForm({ onSuccessPath }: ApplicationFormProps = {}) {
  const {
    register,
    errors,
    watch,
    step,
    setStep,
    totalSteps,
    user,
    profile,
    profileLoading,
    isCustomer,
    onSubmit,
    goNext,
    goPrev,
    submitting,
    submitError,
  } = useApplicationForm(onSuccessPath)

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

      {step === 1 && <PersonalStep register={register} errors={errors} user={user} />}
      {step === 2 && <EmploymentStep register={register} errors={errors} />}
      {step === 3 && <ExpensesStep register={register} errors={errors} />}
      {step === 4 && <LoanDetailsStep register={register} errors={errors} watch={watch} />}
      {step === 5 && <ReviewStep watch={watch} user={user} />}

      {/* Navigation */}
      <div className="flex justify-between">
        <Button
          type="button"
          variant="outline"
          onClick={goPrev}
          disabled={step === 1}
        >
          Previous
        </Button>
        {step < totalSteps ? (
          <Button type="button" onClick={goNext}>
            Next
          </Button>
        ) : (
          <Button type="button" onClick={onSubmit} disabled={submitting}>
            {submitting ? 'Submitting...' : 'Submit Application'}
          </Button>
        )}
      </div>

      {submitError && (
        <p className="text-sm text-destructive text-center">
          Failed to submit application. Please try again.
        </p>
      )}
    </div>
  )
}
