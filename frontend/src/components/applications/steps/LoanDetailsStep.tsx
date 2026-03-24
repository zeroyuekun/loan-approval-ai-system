import { UseFormRegister, FieldErrors, UseFormWatch } from 'react-hook-form'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectItem } from '@/components/ui/select'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { FormData } from '@/hooks/useApplicationForm'

interface LoanDetailsStepProps {
  register: UseFormRegister<FormData>
  errors: FieldErrors<FormData>
  watch: UseFormWatch<FormData>
}

export function LoanDetailsStep({ register, errors, watch }: LoanDetailsStepProps) {
  const purpose = watch('purpose')

  return (
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
  )
}
