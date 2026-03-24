import { UseFormRegister, FieldErrors } from 'react-hook-form'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { FormData } from '@/hooks/useApplicationForm'

interface ExpensesStepProps {
  register: UseFormRegister<FormData>
  errors: FieldErrors<FormData>
}

export function ExpensesStep({ register, errors }: ExpensesStepProps) {
  return (
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
  )
}
