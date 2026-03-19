'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { authApi } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { CustomerProfile } from '@/types'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectItem } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Save, UserCircle, Briefcase, Landmark, Home, CheckCircle2, Lock, ArrowLeft } from 'lucide-react'
import Link from 'next/link'

export default function EditProfilePage() {
  const { user } = useAuth()
  const router = useRouter()
  const queryClient = useQueryClient()
  const [saved, setSaved] = useState(false)

  const { data: profile, isLoading } = useQuery<CustomerProfile>({
    queryKey: ['customerProfile'],
    queryFn: async () => {
      const { data } = await authApi.getCustomerProfile()
      return data
    },
  })

  const [form, setForm] = useState<Partial<CustomerProfile>>({})

  useEffect(() => {
    if (profile) {
      setForm({
        phone: profile.phone || '',
        address_line_1: profile.address_line_1 || '',
        address_line_2: profile.address_line_2 || '',
        suburb: profile.suburb || '',
        state: profile.state || '',
        postcode: profile.postcode || '',
        marital_status: profile.marital_status || '',
        employer_name: profile.employer_name || '',
        occupation: profile.occupation || '',
        industry: profile.industry || '',
        employment_status: profile.employment_status || '',
        years_in_current_role: profile.years_in_current_role ?? undefined,
        previous_employer: profile.previous_employer || '',
        gross_annual_income: profile.gross_annual_income ?? undefined,
        other_income: profile.other_income ?? undefined,
        other_income_source: profile.other_income_source || '',
        partner_annual_income: profile.partner_annual_income ?? undefined,
        estimated_property_value: profile.estimated_property_value ?? undefined,
        vehicle_value: profile.vehicle_value ?? undefined,
        savings_other_institutions: profile.savings_other_institutions ?? undefined,
        investment_value: profile.investment_value ?? undefined,
        superannuation_balance: profile.superannuation_balance ?? undefined,
        other_loan_repayments_monthly: profile.other_loan_repayments_monthly ?? undefined,
        other_credit_card_limits: profile.other_credit_card_limits ?? undefined,
        rent_or_board_monthly: profile.rent_or_board_monthly ?? undefined,
        housing_situation: profile.housing_situation || '',
        time_at_current_address_years: profile.time_at_current_address_years ?? undefined,
        number_of_dependants: profile.number_of_dependants ?? undefined,
        previous_suburb: profile.previous_suburb || '',
        previous_state: profile.previous_state || '',
        previous_postcode: profile.previous_postcode || '',
        preferred_contact_method: profile.preferred_contact_method || '',
      })
    }
  }, [profile])

  const updateProfile = useMutation({
    mutationFn: async (data: Partial<CustomerProfile>) => {
      const { data: result } = await authApi.updateCustomerProfile(data)
      return result
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['customerProfile'] })
      setSaved(true)
      setTimeout(() => {
        router.push('/apply')
      }, 1000)
    },
  })

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target
    setForm(prev => ({ ...prev, [name]: value }))
  }

  const handleSave = () => {
    updateProfile.mutate(form)
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link href="/apply">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back
          </Button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Edit Profile</h1>
          <p className="text-muted-foreground">Update your contact, employment, and financial details</p>
        </div>
      </div>

      {saved && (
        <div className="rounded-lg bg-green-50 border border-green-200 p-3 flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-green-600" />
          <p className="text-sm text-green-800">Profile updated successfully.</p>
        </div>
      )}

      {updateProfile.isError && (
        <div className="rounded-lg bg-destructive/10 border border-destructive/20 p-3">
          <p className="text-sm text-destructive">Failed to save profile. Please check your details and try again.</p>
        </div>
      )}

      {/* Locked Fields Notice */}
      <Card className="border-slate-200 bg-slate-50/50">
        <CardContent className="flex items-start gap-3 py-4">
          <Lock className="h-5 w-5 text-slate-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-slate-700">Some details cannot be changed online</p>
            <p className="text-sm text-slate-500">
              To update your name, date of birth, or identity documents, please visit a branch or contact us.
              This is required under the AML/CTF Act 2006 to prevent identity fraud.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Locked Personal Details */}
      <Card className="opacity-75">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Lock className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-base">Personal Details (Locked)</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Full Name</Label>
              <Input value={`${user?.first_name || ''} ${user?.last_name || ''}`} disabled />
            </div>
            <div>
              <Label>Email</Label>
              <Input value={user?.email || ''} disabled />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Date of Birth</Label>
              <Input value={profile?.date_of_birth || ''} disabled />
            </div>
            <div>
              <Label>Residency Status</Label>
              <Input value={profile?.residency_status ? profile.residency_status.replace(/_/g, ' ') : ''} disabled className="capitalize" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Primary ID</Label>
              <Input value={profile?.primary_id_type ? `${profile.primary_id_type.replace(/_/g, ' ')} ****` : ''} disabled className="capitalize" />
            </div>
            <div>
              <Label>Secondary ID</Label>
              <Input value={profile?.secondary_id_type ? `${profile.secondary_id_type.replace(/_/g, ' ')} ****` : ''} disabled className="capitalize" />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Editable: Contact & Address */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <UserCircle className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Contact &amp; Address</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="phone">Phone Number</Label>
              <Input id="phone" name="phone" value={(form.phone as string) || ''} onChange={handleChange} placeholder="04XX XXX XXX" />
            </div>
            <div>
              <Label htmlFor="preferred_contact_method">Preferred Contact</Label>
              <Select id="preferred_contact_method" name="preferred_contact_method" value={(form.preferred_contact_method as string) || ''} onChange={handleChange}>
                <SelectItem value="">Select...</SelectItem>
                <SelectItem value="email">Email</SelectItem>
                <SelectItem value="phone">Phone</SelectItem>
                <SelectItem value="sms">SMS</SelectItem>
              </Select>
            </div>
          </div>
          <div>
            <Label htmlFor="marital_status">Marital Status</Label>
            <Select id="marital_status" name="marital_status" value={(form.marital_status as string) || ''} onChange={handleChange}>
              <SelectItem value="">Select...</SelectItem>
              <SelectItem value="single">Single</SelectItem>
              <SelectItem value="married">Married</SelectItem>
              <SelectItem value="de_facto">De Facto</SelectItem>
              <SelectItem value="divorced">Divorced</SelectItem>
              <SelectItem value="widowed">Widowed</SelectItem>
            </Select>
          </div>
          <div>
            <Label htmlFor="address_line_1">Street Address</Label>
            <Input id="address_line_1" name="address_line_1" value={(form.address_line_1 as string) || ''} onChange={handleChange} />
          </div>
          <div>
            <Label htmlFor="address_line_2">Address Line 2</Label>
            <Input id="address_line_2" name="address_line_2" value={(form.address_line_2 as string) || ''} onChange={handleChange} placeholder="Unit/Apartment (optional)" />
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <Label htmlFor="suburb">Suburb</Label>
              <Input id="suburb" name="suburb" value={(form.suburb as string) || ''} onChange={handleChange} />
            </div>
            <div>
              <Label htmlFor="state">State</Label>
              <Select id="state" name="state" value={(form.state as string) || ''} onChange={handleChange}>
                <SelectItem value="">Select...</SelectItem>
                <SelectItem value="NSW">NSW</SelectItem>
                <SelectItem value="VIC">VIC</SelectItem>
                <SelectItem value="QLD">QLD</SelectItem>
                <SelectItem value="WA">WA</SelectItem>
                <SelectItem value="SA">SA</SelectItem>
                <SelectItem value="TAS">TAS</SelectItem>
                <SelectItem value="ACT">ACT</SelectItem>
                <SelectItem value="NT">NT</SelectItem>
              </Select>
            </div>
            <div>
              <Label htmlFor="postcode">Postcode</Label>
              <Input id="postcode" name="postcode" value={(form.postcode as string) || ''} onChange={handleChange} />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Editable: Employment & Income */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Briefcase className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Employment &amp; Income</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="employment_status">Employment Status</Label>
              <Select id="employment_status" name="employment_status" value={(form.employment_status as string) || ''} onChange={handleChange}>
                <SelectItem value="">Select...</SelectItem>
                <SelectItem value="payg_permanent">PAYG Permanent</SelectItem>
                <SelectItem value="payg_casual">PAYG Casual</SelectItem>
                <SelectItem value="self_employed">Self Employed</SelectItem>
                <SelectItem value="contract">Contract</SelectItem>
                <SelectItem value="retired">Retired</SelectItem>
                <SelectItem value="unemployed">Unemployed</SelectItem>
                <SelectItem value="home_duties">Home Duties</SelectItem>
              </Select>
            </div>
            <div>
              <Label htmlFor="employer_name">Employer Name</Label>
              <Input id="employer_name" name="employer_name" value={(form.employer_name as string) || ''} onChange={handleChange} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="occupation">Occupation</Label>
              <Input id="occupation" name="occupation" value={(form.occupation as string) || ''} onChange={handleChange} />
            </div>
            <div>
              <Label htmlFor="industry">Industry</Label>
              <Select id="industry" name="industry" value={(form.industry as string) || ''} onChange={handleChange}>
                <SelectItem value="">Select...</SelectItem>
                <SelectItem value="agriculture">Agriculture</SelectItem>
                <SelectItem value="mining">Mining</SelectItem>
                <SelectItem value="manufacturing">Manufacturing</SelectItem>
                <SelectItem value="construction">Construction</SelectItem>
                <SelectItem value="retail_trade">Retail Trade</SelectItem>
                <SelectItem value="financial_insurance">Financial &amp; Insurance</SelectItem>
                <SelectItem value="professional_scientific">Professional &amp; Scientific</SelectItem>
                <SelectItem value="education_training">Education &amp; Training</SelectItem>
                <SelectItem value="healthcare_social">Healthcare &amp; Social</SelectItem>
                <SelectItem value="information_media">Information &amp; Media</SelectItem>
                <SelectItem value="public_admin">Public Administration</SelectItem>
                <SelectItem value="other_services">Other Services</SelectItem>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="years_in_current_role">Years in Current Role</Label>
              <Input id="years_in_current_role" name="years_in_current_role" type="number" value={form.years_in_current_role ?? ''} onChange={handleChange} />
            </div>
            <div>
              <Label htmlFor="gross_annual_income">Gross Annual Income (A$)</Label>
              <Input id="gross_annual_income" name="gross_annual_income" type="number" step="0.01" value={form.gross_annual_income ?? ''} onChange={handleChange} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="other_income">Other Income (A$)</Label>
              <Input id="other_income" name="other_income" type="number" step="0.01" value={form.other_income ?? ''} onChange={handleChange} />
            </div>
            {Number(form.other_income) > 0 && (
              <div>
                <Label htmlFor="other_income_source">Other Income Source</Label>
                <Input id="other_income_source" name="other_income_source" value={(form.other_income_source as string) || ''} onChange={handleChange} />
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Editable: Assets & Liabilities */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Landmark className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Assets &amp; Liabilities</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Assets</Label>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="estimated_property_value">Property Value (A$)</Label>
              <Input id="estimated_property_value" name="estimated_property_value" type="number" step="0.01" value={form.estimated_property_value ?? ''} onChange={handleChange} />
            </div>
            <div>
              <Label htmlFor="vehicle_value">Vehicle Value (A$)</Label>
              <Input id="vehicle_value" name="vehicle_value" type="number" step="0.01" value={form.vehicle_value ?? ''} onChange={handleChange} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="savings_other_institutions">Savings at Other Institutions (A$)</Label>
              <Input id="savings_other_institutions" name="savings_other_institutions" type="number" step="0.01" value={form.savings_other_institutions ?? ''} onChange={handleChange} />
            </div>
            <div>
              <Label htmlFor="superannuation_balance">Superannuation (A$)</Label>
              <Input id="superannuation_balance" name="superannuation_balance" type="number" step="0.01" value={form.superannuation_balance ?? ''} onChange={handleChange} />
            </div>
          </div>
          <div className="border-t pt-4">
            <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Liabilities</Label>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="other_loan_repayments_monthly">Other Loan Repayments Monthly (A$)</Label>
              <Input id="other_loan_repayments_monthly" name="other_loan_repayments_monthly" type="number" step="0.01" value={form.other_loan_repayments_monthly ?? ''} onChange={handleChange} />
            </div>
            <div>
              <Label htmlFor="other_credit_card_limits">Other Credit Card Limits (A$)</Label>
              <Input id="other_credit_card_limits" name="other_credit_card_limits" type="number" step="0.01" value={form.other_credit_card_limits ?? ''} onChange={handleChange} />
            </div>
          </div>
          <div>
            <Label htmlFor="rent_or_board_monthly">Rent or Board Monthly (A$)</Label>
            <Input id="rent_or_board_monthly" name="rent_or_board_monthly" type="number" step="0.01" value={form.rent_or_board_monthly ?? ''} onChange={handleChange} />
          </div>
        </CardContent>
      </Card>

      {/* Editable: Living Situation */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Home className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Living Situation</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="housing_situation">Housing Situation</Label>
              <Select id="housing_situation" name="housing_situation" value={(form.housing_situation as string) || ''} onChange={handleChange}>
                <SelectItem value="">Select...</SelectItem>
                <SelectItem value="own_outright">Own Outright</SelectItem>
                <SelectItem value="mortgage">Mortgage</SelectItem>
                <SelectItem value="renting">Renting</SelectItem>
                <SelectItem value="boarding">Boarding</SelectItem>
                <SelectItem value="living_with_parents">Living with Parents</SelectItem>
              </Select>
            </div>
            <div>
              <Label htmlFor="number_of_dependants">Number of Dependants</Label>
              <Input id="number_of_dependants" name="number_of_dependants" type="number" min="0" max="15" value={form.number_of_dependants ?? ''} onChange={handleChange} />
            </div>
          </div>
          <div>
            <Label htmlFor="time_at_current_address_years">Time at Current Address (years)</Label>
            <Input id="time_at_current_address_years" name="time_at_current_address_years" type="number" value={form.time_at_current_address_years ?? ''} onChange={handleChange} />
          </div>
        </CardContent>
      </Card>

      {/* Save button */}
      <div className="flex justify-end pb-8">
        <Button onClick={handleSave} disabled={updateProfile.isPending} size="lg">
          <Save className="mr-2 h-4 w-4" />
          {updateProfile.isPending ? 'Saving...' : saved ? 'Saved!' : 'Save Changes'}
        </Button>
      </div>
    </div>
  )
}
