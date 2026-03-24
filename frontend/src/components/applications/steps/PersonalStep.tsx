import { UseFormRegister, FieldErrors } from 'react-hook-form'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectItem } from '@/components/ui/select'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { FormData } from '@/hooks/useApplicationForm'

interface PersonalStepProps {
  register: UseFormRegister<FormData>
  errors: FieldErrors<FormData>
  user: { first_name?: string; last_name?: string; email?: string } | null
}

export function PersonalStep({ register, errors, user }: PersonalStepProps) {
  return (
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
  )
}
