import { UseFormRegister, FieldErrors } from 'react-hook-form'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectItem } from '@/components/ui/select'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { FormData } from '@/hooks/useApplicationForm'

interface EmploymentStepProps {
  register: UseFormRegister<FormData>
  errors: FieldErrors<FormData>
}

export function EmploymentStep({ register, errors }: EmploymentStepProps) {
  return (
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
  )
}
