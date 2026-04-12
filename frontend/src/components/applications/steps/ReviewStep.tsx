import { UseFormWatch } from 'react-hook-form'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { FormData } from '@/hooks/useApplicationForm'

interface ReviewStepProps {
  watch: UseFormWatch<FormData>
  user: { first_name?: string; last_name?: string } | null
}

const formatAUD = (value: number | undefined | null) => {
  if (value == null || isNaN(value)) return '\u2014'
  return `A$${Number(value).toLocaleString('en-AU')}`
}

export function ReviewStep({ watch, user }: ReviewStepProps) {
  // Single watch() call subscribes to all fields once, instead of 22
  // individual subscriptions that each trigger a full re-render (perf fix).
  const v = watch()

  return (
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
            <div className="capitalize">{v.applicant_type} ({v.number_of_dependants} dependants)</div>
            <div className="text-muted-foreground">Living Situation</div>
            <div className="capitalize">{v.home_ownership}</div>
          </div>
        </div>
        <hr />

        {/* Employment & Income */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Employment &amp; Income</h4>
          <div className="grid grid-cols-2 gap-x-8 gap-y-1.5">
            <div className="text-muted-foreground">Employment Type</div>
            <div>{v.employment_type?.replace(/_/g, ' ').replace(/payg/i, 'PAYG')}</div>
            <div className="text-muted-foreground">Time in Current Role</div>
            <div>{v.employment_length} years</div>
            <div className="text-muted-foreground">Gross Annual Income</div>
            <div>{formatAUD(v.annual_income)}</div>
            <div className="text-muted-foreground">Equifax Score</div>
            <div>{v.credit_score || '\u2014'}</div>
          </div>
        </div>
        <hr />

        {/* Expenses & Debts */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Expenses &amp; Debts</h4>
          <div className="grid grid-cols-2 gap-x-8 gap-y-1.5">
            <div className="text-muted-foreground">Monthly Living Expenses</div>
            <div>{v.monthly_expenses ? formatAUD(v.monthly_expenses) : 'HEM benchmark'}</div>
            <div className="text-muted-foreground">Total Credit Card Limits</div>
            <div>{formatAUD(v.existing_credit_card_limit)}</div>
            <div className="text-muted-foreground">DTI Ratio</div>
            <div>{v.debt_to_income}x</div>
            <div className="text-muted-foreground">HECS/HELP Debt</div>
            <div>{v.has_hecs ? 'Yes' : 'No'}</div>
            <div className="text-muted-foreground">Bankruptcy History</div>
            <div>{v.has_bankruptcy ? 'Yes' : 'No'}</div>
          </div>
        </div>
        <hr />

        {/* Loan Details */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Loan Details</h4>
          <div className="grid grid-cols-2 gap-x-8 gap-y-1.5">
            <div className="text-muted-foreground">Loan Amount</div>
            <div className="font-semibold">{formatAUD(v.loan_amount)}</div>
            <div className="text-muted-foreground">Loan Term</div>
            <div>{v.loan_term_months} months</div>
            <div className="text-muted-foreground">Purpose</div>
            <div className="capitalize">{v.purpose}</div>
            {v.purpose === 'home' && (
              <>
                <div className="text-muted-foreground">Property Value</div>
                <div>{formatAUD(v.property_value)}</div>
                <div className="text-muted-foreground">Deposit</div>
                <div>{formatAUD(v.deposit_amount)}</div>
                <div className="text-muted-foreground">Estimated LVR</div>
                <div>
                  {v.property_value && Number(v.property_value) > 0
                    ? `${((Number(v.loan_amount) / Number(v.property_value)) * 100).toFixed(1)}%`
                    : '\u2014'}
                </div>
              </>
            )}
            <div className="text-muted-foreground">Guarantor / Co-borrower</div>
            <div>{v.has_cosigner ? 'Yes' : 'No'}</div>
          </div>
        </div>

        {v.notes && (
          <>
            <hr />
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Notes</h4>
              <p className="text-muted-foreground">{v.notes}</p>
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
  )
}
