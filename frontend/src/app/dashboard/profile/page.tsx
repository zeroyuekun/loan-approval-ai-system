'use client'

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { authApi } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { CustomerProfile } from '@/types'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectItem } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Save, Shield, UserCircle, Building2, CreditCard, Briefcase, Landmark, Home } from 'lucide-react'

export default function ProfilePage() {
  const { user } = useAuth()
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
        date_of_birth: profile.date_of_birth || '',
        phone: profile.phone || '',
        address_line_1: profile.address_line_1 || '',
        address_line_2: profile.address_line_2 || '',
        suburb: profile.suburb || '',
        state: profile.state || '',
        postcode: profile.postcode || '',
        marital_status: profile.marital_status || '',
        residency_status: profile.residency_status || '',
        primary_id_type: profile.primary_id_type || '',
        primary_id_number: profile.primary_id_number || '',
        secondary_id_type: profile.secondary_id_type || '',
        secondary_id_number: profile.secondary_id_number || '',
        tax_file_number_provided: profile.tax_file_number_provided || false,
        is_politically_exposed: profile.is_politically_exposed || false,
        // Employment
        employer_name: profile.employer_name || '',
        occupation: profile.occupation || '',
        industry: profile.industry || '',
        employment_status: profile.employment_status || '',
        years_in_current_role: profile.years_in_current_role || 0,
        previous_employer: profile.previous_employer || '',
        // Income
        gross_annual_income: profile.gross_annual_income || 0,
        other_income: profile.other_income || 0,
        other_income_source: profile.other_income_source || '',
        partner_annual_income: profile.partner_annual_income || 0,
        // Assets
        estimated_property_value: profile.estimated_property_value || 0,
        vehicle_value: profile.vehicle_value || 0,
        savings_other_institutions: profile.savings_other_institutions || 0,
        investment_value: profile.investment_value || 0,
        superannuation_balance: profile.superannuation_balance || 0,
        // Liabilities
        other_loan_repayments_monthly: profile.other_loan_repayments_monthly || 0,
        other_credit_card_limits: profile.other_credit_card_limits || 0,
        rent_or_board_monthly: profile.rent_or_board_monthly || 0,
        // Living Situation
        housing_situation: profile.housing_situation || '',
        time_at_current_address_years: profile.time_at_current_address_years || 0,
        number_of_dependants: profile.number_of_dependants || 0,
        previous_suburb: profile.previous_suburb || '',
        previous_state: profile.previous_state || '',
        previous_postcode: profile.previous_postcode || '',
        // Contact
        preferred_contact_method: profile.preferred_contact_method || '',
      })
    }
  }, [profile])

  const updateProfile = useMutation({
    mutationFn: async (data: Partial<CustomerProfile>) => {
      const { data: result } = await authApi.updateCustomerProfile(data)
      return result
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['customerProfile'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
  })

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target
    const checked = (e.target as HTMLInputElement).checked
    setForm(prev => ({ ...prev, [name]: type === 'checkbox' ? checked : value }))
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

  const tierColors: Record<string, string> = {
    standard: 'bg-gray-100 text-gray-800',
    silver: 'bg-slate-200 text-slate-800',
    gold: 'bg-yellow-100 text-yellow-800',
    platinum: 'bg-purple-100 text-purple-800',
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">My Profile</h1>
          <p className="text-muted-foreground">Personal details and compliance information</p>
        </div>
        <Button onClick={handleSave} disabled={updateProfile.isPending}>
          <Save className="mr-2 h-4 w-4" />
          {updateProfile.isPending ? 'Saving...' : saved ? 'Saved!' : 'Save Changes'}
        </Button>
      </div>

      {updateProfile.isError && (
        <div className="rounded-lg bg-destructive/10 border border-destructive/20 p-3">
          <p className="text-sm text-destructive">Failed to save profile. Please check your details and try again.</p>
        </div>
      )}

      {/* Banking Overview (read-only) */}
      {profile && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <CreditCard className="h-5 w-5 text-muted-foreground" />
                <CardTitle className="text-base">Banking Relationship</CardTitle>
              </div>
              <Badge className={tierColors[profile.loyalty_tier] || ''} variant="outline">
                {profile.loyalty_tier.charAt(0).toUpperCase() + profile.loyalty_tier.slice(1)} Tier
              </Badge>
            </div>
            <CardDescription>Your banking history with AussieLoanAI. These details are managed by the bank.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
              <div className="rounded-lg bg-muted/50 p-3">
                <p className="text-muted-foreground text-xs">Account Tenure</p>
                <p className="font-semibold">{profile.account_tenure_years} years</p>
              </div>
              <div className="rounded-lg bg-muted/50 p-3">
                <p className="text-muted-foreground text-xs">Products Held</p>
                <p className="font-semibold">{profile.num_products}</p>
              </div>
              <div className="rounded-lg bg-muted/50 p-3">
                <p className="text-muted-foreground text-xs">On-Time Payments</p>
                <p className="font-semibold">{profile.on_time_payment_pct.toFixed(1)}%</p>
              </div>
              <div className="rounded-lg bg-muted/50 p-3">
                <p className="text-muted-foreground text-xs">Loans Repaid</p>
                <p className="font-semibold">{profile.previous_loans_repaid}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Personal Details */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <UserCircle className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Personal Details</CardTitle>
          </div>
          <CardDescription>Required under the National Consumer Credit Protection Act 2009 (NCCP) for responsible lending assessment.</CardDescription>
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
              <Label htmlFor="date_of_birth">Date of Birth</Label>
              <Input id="date_of_birth" name="date_of_birth" type="date" value={(form.date_of_birth as string) || ''} onChange={handleChange} />
            </div>
            <div>
              <Label htmlFor="phone">Phone Number</Label>
              <Input id="phone" name="phone" value={(form.phone as string) || ''} onChange={handleChange} placeholder="04XX XXX XXX" />
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

          <div className="pt-2">
            <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Residential Address</Label>
          </div>
          <div>
            <Label htmlFor="address_line_1">Street Address</Label>
            <Input id="address_line_1" name="address_line_1" value={(form.address_line_1 as string) || ''} onChange={handleChange} placeholder="123 Example Street" />
          </div>
          <div>
            <Label htmlFor="address_line_2">Address Line 2</Label>
            <Input id="address_line_2" name="address_line_2" value={(form.address_line_2 as string) || ''} onChange={handleChange} placeholder="Unit/Apartment (optional)" />
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <Label htmlFor="suburb">Suburb</Label>
              <Input id="suburb" name="suburb" value={(form.suburb as string) || ''} onChange={handleChange} placeholder="Sydney" />
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
              <Input id="postcode" name="postcode" value={(form.postcode as string) || ''} onChange={handleChange} placeholder="2000" />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Employment & Income */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Briefcase className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Employment &amp; Income</CardTitle>
          </div>
          <CardDescription>Required for responsible lending assessment under NCCP Act. We need to verify your ability to service loan repayments.</CardDescription>
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
              <Input id="employer_name" name="employer_name" value={(form.employer_name as string) || ''} onChange={handleChange} placeholder="e.g. Commonwealth Bank" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="occupation">Occupation</Label>
              <Input id="occupation" name="occupation" value={(form.occupation as string) || ''} onChange={handleChange} placeholder="e.g. Software Engineer" />
            </div>
            <div>
              <Label htmlFor="industry">Industry</Label>
              <Select id="industry" name="industry" value={(form.industry as string) || ''} onChange={handleChange}>
                <SelectItem value="">Select...</SelectItem>
                <SelectItem value="agriculture">Agriculture</SelectItem>
                <SelectItem value="mining">Mining</SelectItem>
                <SelectItem value="manufacturing">Manufacturing</SelectItem>
                <SelectItem value="utilities">Utilities</SelectItem>
                <SelectItem value="construction">Construction</SelectItem>
                <SelectItem value="wholesale_trade">Wholesale Trade</SelectItem>
                <SelectItem value="retail_trade">Retail Trade</SelectItem>
                <SelectItem value="accommodation_food">Accommodation &amp; Food</SelectItem>
                <SelectItem value="transport_postal">Transport &amp; Postal</SelectItem>
                <SelectItem value="information_media">Information &amp; Media</SelectItem>
                <SelectItem value="financial_insurance">Financial &amp; Insurance</SelectItem>
                <SelectItem value="property_services">Property Services</SelectItem>
                <SelectItem value="professional_scientific">Professional &amp; Scientific</SelectItem>
                <SelectItem value="administrative">Administrative</SelectItem>
                <SelectItem value="public_admin">Public Administration</SelectItem>
                <SelectItem value="education_training">Education &amp; Training</SelectItem>
                <SelectItem value="healthcare_social">Healthcare &amp; Social</SelectItem>
                <SelectItem value="arts_recreation">Arts &amp; Recreation</SelectItem>
                <SelectItem value="other_services">Other Services</SelectItem>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="years_in_current_role">Years in Current Role</Label>
              <Input id="years_in_current_role" name="years_in_current_role" type="number" value={form.years_in_current_role || ''} onChange={handleChange} placeholder="0" />
            </div>
          </div>
          {Number(form.years_in_current_role) < 2 && (
            <div>
              <Label htmlFor="previous_employer">Previous Employer</Label>
              <Input id="previous_employer" name="previous_employer" value={(form.previous_employer as string) || ''} onChange={handleChange} placeholder="e.g. Westpac" />
            </div>
          )}

          <div className="pt-2">
            <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Income Details</Label>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="gross_annual_income">Gross Annual Income (A$)</Label>
              <Input id="gross_annual_income" name="gross_annual_income" type="number" step="0.01" value={form.gross_annual_income || ''} onChange={handleChange} placeholder="0.00" />
            </div>
            <div>
              <Label htmlFor="other_income">Other Income (A$)</Label>
              <Input id="other_income" name="other_income" type="number" step="0.01" value={form.other_income || ''} onChange={handleChange} placeholder="0.00" />
            </div>
          </div>
          {Number(form.other_income) > 0 && (
            <div>
              <Label htmlFor="other_income_source">Other Income Source</Label>
              <Input id="other_income_source" name="other_income_source" value={(form.other_income_source as string) || ''} onChange={handleChange} placeholder="e.g. Rental income, Dividends" />
            </div>
          )}
          {(form.marital_status === 'married' || form.marital_status === 'de_facto') && (
            <div>
              <Label htmlFor="partner_annual_income">Partner Annual Income (A$)</Label>
              <Input id="partner_annual_income" name="partner_annual_income" type="number" step="0.01" value={form.partner_annual_income || ''} onChange={handleChange} placeholder="0.00" />
            </div>
          )}
        </CardContent>
      </Card>

      {/* Assets & Liabilities */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Landmark className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Assets &amp; Liabilities</CardTitle>
          </div>
          <CardDescription>Your financial position is assessed as part of the responsible lending obligation under the NCCP Act.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="pt-0">
            <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Assets</Label>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="estimated_property_value">Estimated Property Value (A$)</Label>
              <Input id="estimated_property_value" name="estimated_property_value" type="number" step="0.01" value={form.estimated_property_value || ''} onChange={handleChange} placeholder="0.00" />
            </div>
            <div>
              <Label htmlFor="vehicle_value">Vehicle Value (A$)</Label>
              <Input id="vehicle_value" name="vehicle_value" type="number" step="0.01" value={form.vehicle_value || ''} onChange={handleChange} placeholder="0.00" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="savings_other_institutions">Savings at Other Institutions (A$)</Label>
              <Input id="savings_other_institutions" name="savings_other_institutions" type="number" step="0.01" value={form.savings_other_institutions || ''} onChange={handleChange} placeholder="0.00" />
            </div>
            <div>
              <Label htmlFor="investment_value">Investment Value (A$)</Label>
              <Input id="investment_value" name="investment_value" type="number" step="0.01" value={form.investment_value || ''} onChange={handleChange} placeholder="0.00" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="superannuation_balance">Superannuation Balance (A$)</Label>
              <Input id="superannuation_balance" name="superannuation_balance" type="number" step="0.01" value={form.superannuation_balance || ''} onChange={handleChange} placeholder="0.00" />
            </div>
          </div>
          {profile && (
            <div className="rounded-lg bg-muted/50 p-3 text-sm">
              <span className="text-muted-foreground">Total Assets: </span>
              <span className="font-semibold">A$ {(profile.total_assets ?? 0).toLocaleString('en-AU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
            </div>
          )}

          <div className="border-t pt-4">
            <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Liabilities</Label>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="other_loan_repayments_monthly">Other Loan Repayments Monthly (A$)</Label>
              <Input id="other_loan_repayments_monthly" name="other_loan_repayments_monthly" type="number" step="0.01" value={form.other_loan_repayments_monthly || ''} onChange={handleChange} placeholder="0.00" />
            </div>
            <div>
              <Label htmlFor="other_credit_card_limits">Other Credit Card Limits (A$)</Label>
              <Input id="other_credit_card_limits" name="other_credit_card_limits" type="number" step="0.01" value={form.other_credit_card_limits || ''} onChange={handleChange} placeholder="0.00" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="rent_or_board_monthly">Rent or Board Monthly (A$)</Label>
              <Input id="rent_or_board_monthly" name="rent_or_board_monthly" type="number" step="0.01" value={form.rent_or_board_monthly || ''} onChange={handleChange} placeholder="0.00" />
            </div>
          </div>
          {profile && (
            <div className="rounded-lg bg-muted/50 p-3 text-sm">
              <span className="text-muted-foreground">Total Monthly Liabilities: </span>
              <span className="font-semibold">A$ {(profile.total_monthly_liabilities ?? 0).toLocaleString('en-AU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Living Situation */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Home className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Living Situation</CardTitle>
          </div>
          <CardDescription>Housing and dependant details help us assess your ongoing financial commitments.</CardDescription>
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
              <Label htmlFor="time_at_current_address_years">Time at Current Address (years)</Label>
              <Input id="time_at_current_address_years" name="time_at_current_address_years" type="number" value={form.time_at_current_address_years || ''} onChange={handleChange} placeholder="0" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="number_of_dependants">Number of Dependants</Label>
              <Input id="number_of_dependants" name="number_of_dependants" type="number" min="0" max="15" value={form.number_of_dependants || ''} onChange={handleChange} placeholder="0" />
            </div>
            <div>
              <Label htmlFor="preferred_contact_method">Preferred Contact Method</Label>
              <Select id="preferred_contact_method" name="preferred_contact_method" value={(form.preferred_contact_method as string) || ''} onChange={handleChange}>
                <SelectItem value="">Select...</SelectItem>
                <SelectItem value="email">Email</SelectItem>
                <SelectItem value="phone">Phone</SelectItem>
                <SelectItem value="sms">SMS</SelectItem>
              </Select>
            </div>
          </div>
          {Number(form.time_at_current_address_years) < 3 && (
            <>
              <div className="pt-2">
                <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Previous Address</Label>
              </div>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <Label htmlFor="previous_suburb">Previous Suburb</Label>
                  <Input id="previous_suburb" name="previous_suburb" value={(form.previous_suburb as string) || ''} onChange={handleChange} placeholder="Melbourne" />
                </div>
                <div>
                  <Label htmlFor="previous_state">Previous State</Label>
                  <Select id="previous_state" name="previous_state" value={(form.previous_state as string) || ''} onChange={handleChange}>
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
                  <Label htmlFor="previous_postcode">Previous Postcode</Label>
                  <Input id="previous_postcode" name="previous_postcode" value={(form.previous_postcode as string) || ''} onChange={handleChange} placeholder="3000" />
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Identity & Compliance */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Identity Verification &amp; Compliance</CardTitle>
          </div>
          <CardDescription>Required under the Anti-Money Laundering and Counter-Terrorism Financing Act 2006 (AML/CTF). Australian lenders must complete a 100-point identity check before processing loan applications.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label htmlFor="residency_status">Residency Status</Label>
            <Select id="residency_status" name="residency_status" value={(form.residency_status as string) || ''} onChange={handleChange}>
              <SelectItem value="">Select...</SelectItem>
              <SelectItem value="citizen">Australian Citizen</SelectItem>
              <SelectItem value="permanent_resident">Permanent Resident</SelectItem>
              <SelectItem value="temporary_visa">Temporary Visa Holder</SelectItem>
              <SelectItem value="nz_citizen">New Zealand Citizen</SelectItem>
            </Select>
            <p className="text-xs text-muted-foreground mt-1">Non-residents may face additional lending restrictions under APRA guidelines.</p>
          </div>

          <div className="pt-2">
            <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Primary ID (70 points)</Label>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="primary_id_type">Document Type</Label>
              <Select id="primary_id_type" name="primary_id_type" value={(form.primary_id_type as string) || ''} onChange={handleChange}>
                <SelectItem value="">Select...</SelectItem>
                <SelectItem value="drivers_licence">Driver's Licence</SelectItem>
                <SelectItem value="passport">Australian Passport</SelectItem>
              </Select>
            </div>
            <div>
              <Label htmlFor="primary_id_number">Document Number</Label>
              <Input id="primary_id_number" name="primary_id_number" value={(form.primary_id_number as string) || ''} onChange={handleChange} placeholder="e.g. 12345678" />
            </div>
          </div>

          <div className="pt-2">
            <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Secondary ID (30+ points)</Label>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="secondary_id_type">Document Type</Label>
              <Select id="secondary_id_type" name="secondary_id_type" value={(form.secondary_id_type as string) || ''} onChange={handleChange}>
                <SelectItem value="">Select...</SelectItem>
                <SelectItem value="medicare">Medicare Card</SelectItem>
                <SelectItem value="drivers_licence">Driver's Licence</SelectItem>
                <SelectItem value="passport">Australian Passport</SelectItem>
                <SelectItem value="immicard">ImmiCard</SelectItem>
              </Select>
            </div>
            <div>
              <Label htmlFor="secondary_id_number">Document Number</Label>
              <Input id="secondary_id_number" name="secondary_id_number" value={(form.secondary_id_number as string) || ''} onChange={handleChange} placeholder="e.g. 2345 67890 1" />
            </div>
          </div>

          <div className="pt-4 space-y-3">
            <div className="flex items-center gap-2">
              <input type="checkbox" id="tax_file_number_provided" name="tax_file_number_provided" className="h-4 w-4 rounded border-input" checked={!!form.tax_file_number_provided} onChange={handleChange} />
              <Label htmlFor="tax_file_number_provided">I have lodged a TFN declaration with AussieLoanAI</Label>
            </div>
            <p className="text-xs text-muted-foreground ml-6">Required for interest-bearing accounts. Your TFN is not stored in this system.</p>

            <div className="flex items-center gap-2">
              <input type="checkbox" id="is_politically_exposed" name="is_politically_exposed" className="h-4 w-4 rounded border-input" checked={!!form.is_politically_exposed} onChange={handleChange} />
              <Label htmlFor="is_politically_exposed">I am a Politically Exposed Person (PEP)</Label>
            </div>
            <p className="text-xs text-muted-foreground ml-6">Under AML/CTF rules, PEPs include government officials, senior political figures, and their associates. Enhanced due diligence may apply.</p>
          </div>
        </CardContent>
      </Card>

      {/* Regulatory Notice */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Building2 className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Regulatory Information</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-3 text-xs text-muted-foreground">
            <p>AussieLoanAI collects personal information in accordance with the <strong>Privacy Act 1988</strong> (Cth) and the <strong>Australian Privacy Principles</strong> (APPs). Your information is used solely for the purpose of assessing loan applications and managing your banking relationship.</p>
            <p>Identity verification is conducted in compliance with the <strong>Anti-Money Laundering and Counter-Terrorism Financing Act 2006</strong> (AML/CTF Act). We are required to verify your identity before providing designated services.</p>
            <p>Loan assessments are conducted in accordance with the <strong>National Consumer Credit Protection Act 2009</strong> (NCCP Act) responsible lending obligations. We assess your capacity to repay without substantial hardship.</p>
            <p>You have the right to access and correct your personal information under the Privacy Act. To make a complaint, contact the <strong>Office of the Australian Information Commissioner (OAIC)</strong> at <strong>www.oaic.gov.au</strong>.</p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
