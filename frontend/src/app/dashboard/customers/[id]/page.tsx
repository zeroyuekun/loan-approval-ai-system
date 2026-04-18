'use client'

import { useState, useEffect, useContext } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { authApi, loansApi } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { StaffCustomerDetail, LoanApplication, CustomerActivity, PaginatedResponse } from '@/types'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectItem } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import { EmailPreview } from '@/components/emails/EmailPreview'
import { WorkflowTimeline } from '@/components/agents/WorkflowTimeline'
import { AgentStepCard } from '@/components/agents/AgentStepCard'
import { NextBestOfferCard } from '@/components/agents/NextBestOfferCard'
import { MarketingEmailCard } from '@/components/agents/MarketingEmailCard'
import { formatCurrency, formatDate, getStatusColor, getDisplayStatus } from '@/lib/utils'
import {
  tierColors,
  residencyLabels,
  idTypeLabels,
  maritalLabels,
  employmentStatusLabels,
  housingSituationLabels,
  industryLabels,
  contactMethodLabels,
} from '@/lib/customerLabels'
import {
  ArrowLeft,
  UserCircle,
  CreditCard,
  Shield,
  Calendar,
  Phone,
  Mail,
  Building2,
  CheckCircle,
  XCircle,
  Bot,
  ChevronDown,
  ChevronRight,
  Pencil,
  Save,
  X,
} from 'lucide-react'

function BoolIndicator({ value, label }: { value: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      {value ? (
        <CheckCircle className="h-4 w-4 text-green-600" aria-hidden="true" />
      ) : (
        <XCircle className="h-4 w-4 text-muted-foreground/40" aria-hidden="true" />
      )}
      <span className="sr-only">{value ? 'Yes' : 'No'}:</span>
      <span className={value ? 'text-sm' : 'text-sm text-muted-foreground'}>{label}</span>
    </div>
  )
}

type EditableFields = {
  // Personal details
  date_of_birth?: string
  phone?: string
  address_line_1?: string
  address_line_2?: string
  suburb?: string
  state?: string
  postcode?: string
  marital_status?: string
  // Identity & compliance
  residency_status?: string
  primary_id_type?: string
  primary_id_number?: string
  secondary_id_type?: string
  secondary_id_number?: string
  tax_file_number_provided?: boolean
  is_politically_exposed?: boolean
  // Banking
  savings_balance?: number
  checking_balance?: number
  account_tenure_years?: number
  loyalty_tier?: string
  num_products?: number
  has_credit_card?: boolean
  has_mortgage?: boolean
  has_auto_loan?: boolean
  on_time_payment_pct?: number
  previous_loans_repaid?: number
  // Employment
  employer_name?: string
  occupation?: string
  industry?: string
  employment_status?: string
  years_in_current_role?: number
  previous_employer?: string
  // Income
  gross_annual_income?: number
  other_income?: number
  other_income_source?: string
  partner_annual_income?: number
  // Assets
  estimated_property_value?: number
  vehicle_value?: number
  savings_other_institutions?: number
  investment_value?: number
  superannuation_balance?: number
  // Liabilities
  other_loan_repayments_monthly?: number
  other_credit_card_limits?: number
  rent_or_board_monthly?: number
  // Living Situation
  housing_situation?: string
  time_at_current_address_years?: number
  number_of_dependants?: number
  previous_suburb?: string
  previous_state?: string
  previous_postcode?: string
  // Contact
  preferred_contact_method?: string
}

function EditableField({
  label,
  value,
  field,
  editing,
  editData,
  onChange,
  type = 'text',
}: {
  label: string
  value: string | number | null | undefined
  field: keyof EditableFields
  editing: boolean
  editData: EditableFields
  onChange: (field: keyof EditableFields, value: any) => void
  type?: 'text' | 'number' | 'date'
}) {
  if (!editing) {
    return (
      <div className="flex justify-between">
        <span className="text-muted-foreground">{label}</span>
        <span>{value ?? '-'}</span>
      </div>
    )
  }
  return (
    <div className="flex justify-between items-center gap-4">
      <span className="text-muted-foreground shrink-0">{label}</span>
      <Input
        type={type}
        value={editData[field] as string ?? ''}
        onChange={(e) => onChange(field, type === 'number' ? Number(e.target.value) : e.target.value)}
        className="max-w-[200px] h-8 text-sm"
      />
    </div>
  )
}

function EditableSelect({
  label,
  value,
  displayValue,
  field,
  editing,
  editData,
  onChange,
  options,
}: {
  label: string
  value: string
  displayValue: string
  field: keyof EditableFields
  editing: boolean
  editData: EditableFields
  onChange: (field: keyof EditableFields, value: any) => void
  options: Record<string, string>
}) {
  if (!editing) {
    return (
      <div className="flex justify-between">
        <span className="text-muted-foreground">{label}</span>
        <span>{displayValue || '-'}</span>
      </div>
    )
  }
  return (
    <div className="flex justify-between items-center gap-4">
      <span className="text-muted-foreground shrink-0">{label}</span>
      <Select
        value={(editData[field] as string) ?? ''}
        onChange={(e) => onChange(field, e.target.value)}
        className="max-w-[200px] h-8 text-sm"
      >
        <SelectItem value="">-- Select --</SelectItem>
        {Object.entries(options).map(([key, optLabel]) => (
          <SelectItem key={key} value={key}>{optLabel}</SelectItem>
        ))}
      </Select>
    </div>
  )
}

function EditableBool({
  value,
  label,
  field,
  editing,
  editData,
  onChange,
}: {
  value: boolean
  label: string
  field: keyof EditableFields
  editing: boolean
  editData: EditableFields
  onChange: (field: keyof EditableFields, value: any) => void
}) {
  if (!editing) {
    return <BoolIndicator value={value} label={label} />
  }
  const checked = (editData[field] as boolean) ?? false
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(field, e.target.checked)}
        className="h-4 w-4 rounded border-gray-300"
      />
      <span className="text-sm">{label}</span>
    </label>
  )
}

export default function CustomerProfilePage() {
  const params = useParams()
  const router = useRouter()
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuth()
  const userId = Number(params.id)
  const [expandedEmail, setExpandedEmail] = useState<string | null>(null)
  const [expandedRun, setExpandedRun] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [editData, setEditData] = useState<EditableFields>({})
  const [saveError, setSaveError] = useState<string | null>(null)

  const isAdmin = currentUser?.role === 'admin'

  const { data: profile, isLoading: profileLoading } = useQuery<StaffCustomerDetail>({
    queryKey: ['customerDetail', userId],
    queryFn: async () => {
      const { data } = await authApi.getCustomerDetail(userId)
      return data
    },
    enabled: !isNaN(userId),
  })

  const { data: loansData, isLoading: loansLoading } = useQuery<PaginatedResponse<LoanApplication>>({
    queryKey: ['customerLoans', userId],
    queryFn: async () => {
      const { data } = await loansApi.list({ applicant: userId, page_size: 50 })
      return data
    },
    enabled: !isNaN(userId),
  })

  const { data: activity, isLoading: activityLoading } = useQuery<CustomerActivity>({
    queryKey: ['customerActivity', userId],
    queryFn: async () => {
      const { data } = await authApi.getCustomerActivity(userId)
      return data
    },
    enabled: !isNaN(userId),
  })

  const updateMutation = useMutation({
    mutationFn: (data: EditableFields) => authApi.updateCustomerDetail(userId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['customerDetail', userId] })
      setEditing(false)
      setSaveError(null)
    },
    onError: (err: any) => {
      setSaveError(err.response?.data?.detail || 'Failed to update profile.')
    },
  })

  const handleEditField = (field: keyof EditableFields, value: any) => {
    setEditData((prev) => ({ ...prev, [field]: value }))
  }

  const startEditing = () => {
    if (!profile) return
    setEditData({
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
      secondary_id_type: profile.secondary_id_type || '',
      tax_file_number_provided: profile.tax_file_number_provided,
      is_politically_exposed: profile.is_politically_exposed,
      savings_balance: Number(profile.savings_balance),
      checking_balance: Number(profile.checking_balance),
      account_tenure_years: profile.account_tenure_years,
      loyalty_tier: profile.loyalty_tier || '',
      num_products: profile.num_products,
      has_credit_card: profile.has_credit_card,
      has_mortgage: profile.has_mortgage,
      has_auto_loan: profile.has_auto_loan,
      on_time_payment_pct: profile.on_time_payment_pct,
      previous_loans_repaid: profile.previous_loans_repaid,
      // Employment
      employer_name: profile.employer_name || '',
      occupation: profile.occupation || '',
      industry: profile.industry || '',
      employment_status: profile.employment_status || '',
      years_in_current_role: profile.years_in_current_role ?? 0,
      previous_employer: profile.previous_employer || '',
      // Income
      gross_annual_income: Number(profile.gross_annual_income) || 0,
      other_income: Number(profile.other_income) || 0,
      other_income_source: profile.other_income_source || '',
      partner_annual_income: Number(profile.partner_annual_income) || 0,
      // Assets
      estimated_property_value: Number(profile.estimated_property_value) || 0,
      vehicle_value: Number(profile.vehicle_value) || 0,
      savings_other_institutions: Number(profile.savings_other_institutions) || 0,
      investment_value: Number(profile.investment_value) || 0,
      superannuation_balance: Number(profile.superannuation_balance) || 0,
      // Liabilities
      other_loan_repayments_monthly: Number(profile.other_loan_repayments_monthly) || 0,
      other_credit_card_limits: Number(profile.other_credit_card_limits) || 0,
      rent_or_board_monthly: Number(profile.rent_or_board_monthly) || 0,
      // Living Situation
      housing_situation: profile.housing_situation || '',
      time_at_current_address_years: profile.time_at_current_address_years ?? 0,
      number_of_dependants: profile.number_of_dependants ?? 0,
      previous_suburb: profile.previous_suburb || '',
      previous_state: profile.previous_state || '',
      previous_postcode: profile.previous_postcode || '',
      // Contact
      preferred_contact_method: profile.preferred_contact_method || '',
    })
    setSaveError(null)
    setEditing(true)
  }

  const cancelEditing = () => {
    setEditing(false)
    setEditData({})
    setSaveError(null)
  }

  const saveChanges = () => {
    updateMutation.mutate(editData)
  }

  if (profileLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-48 w-full" />
        <div className="grid gap-6 md:grid-cols-2">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </div>
    )
  }

  if (!profile) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-muted-foreground">Customer not found</p>
      </div>
    )
  }

  const user = profile.user
  const loans = loansData?.results || []
  const emails = activity?.emails || []
  const agentRuns = activity?.agent_runs || []
  const fullAddress = [profile.address_line_1, profile.address_line_2, profile.suburb, profile.state, profile.postcode]
    .filter(Boolean)
    .join(', ')

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <button
          onClick={() => router.back()}
          className="mt-1 rounded-lg p-2 hover:bg-muted transition-colors"
        >
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight">
              {user.first_name} {user.last_name}
            </h1>
            <Badge className={tierColors[profile.loyalty_tier] || ''} variant="outline">
              {profile.loyalty_tier.charAt(0).toUpperCase() + profile.loyalty_tier.slice(1)} Tier
            </Badge>
          </div>
          <div className="flex items-center gap-4 mt-1 text-sm text-muted-foreground">
            <span className="flex items-center gap-1">
              <Mail className="h-3.5 w-3.5" />
              {user.email}
            </span>
            {profile.phone && (
              <span className="flex items-center gap-1">
                <Phone className="h-3.5 w-3.5" />
                {profile.phone}
              </span>
            )}
            {user.created_at && (
              <span className="flex items-center gap-1">
                <Calendar className="h-3.5 w-3.5" />
                Member since {formatDate(user.created_at)}
              </span>
            )}
          </div>
        </div>
        {isAdmin && !editing && (
          <Button variant="outline" size="sm" onClick={startEditing} className="gap-2">
            <Pencil className="h-4 w-4" />
            Edit Profile
          </Button>
        )}
        {editing && (
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={cancelEditing} className="gap-2">
              <X className="h-4 w-4" />
              Cancel
            </Button>
            <Button size="sm" onClick={saveChanges} disabled={updateMutation.isPending} className="gap-2">
              <Save className="h-4 w-4" />
              {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
            </Button>
          </div>
        )}
      </div>
      {saveError && (
        <div className="rounded-md bg-destructive/10 p-3">
          <p className="text-sm text-destructive">{saveError}</p>
        </div>
      )}

      {/* Banking Relationship */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CreditCard className="h-5 w-5 text-muted-foreground" />
              <CardTitle className="text-base">Banking Relationship</CardTitle>
            </div>
            <span className="text-sm text-muted-foreground">
              {profile.account_tenure_years} year{profile.account_tenure_years !== 1 ? 's' : ''} with AussieLoanAI
            </span>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
            <div className="rounded-lg bg-muted/50 p-3">
              <p className="text-muted-foreground text-xs">Account Tenure</p>
              {editing ? (
                <Input type="number" value={editData.account_tenure_years ?? 0} onChange={(e) => handleEditField('account_tenure_years', Number(e.target.value))} className="h-7 text-sm mt-1" />
              ) : (
                <p className="font-semibold">{profile.account_tenure_years} years</p>
              )}
            </div>
            <div className="rounded-lg bg-muted/50 p-3">
              <p className="text-muted-foreground text-xs">Products Held</p>
              {editing ? (
                <Input type="number" value={editData.num_products ?? 0} onChange={(e) => handleEditField('num_products', Number(e.target.value))} className="h-7 text-sm mt-1" />
              ) : (
                <p className="font-semibold">{profile.num_products}</p>
              )}
            </div>
            <div className="rounded-lg bg-muted/50 p-3">
              <p className="text-muted-foreground text-xs">On-Time Payments</p>
              {editing ? (
                <Input type="number" step="0.1" value={editData.on_time_payment_pct ?? 0} onChange={(e) => handleEditField('on_time_payment_pct', Number(e.target.value))} className="h-7 text-sm mt-1" />
              ) : (
                <p className="font-semibold">{Number(profile.on_time_payment_pct).toFixed(1)}%</p>
              )}
            </div>
            <div className="rounded-lg bg-muted/50 p-3">
              <p className="text-muted-foreground text-xs">Loans Repaid</p>
              {editing ? (
                <Input type="number" value={editData.previous_loans_repaid ?? 0} onChange={(e) => handleEditField('previous_loans_repaid', Number(e.target.value))} className="h-7 text-sm mt-1" />
              ) : (
                <p className="font-semibold">{profile.previous_loans_repaid}</p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mt-4 text-sm">
            <div className="rounded-lg bg-muted/50 p-3">
              <p className="text-muted-foreground text-xs">Savings Balance</p>
              {editing ? (
                <Input type="number" step="0.01" value={editData.savings_balance ?? 0} onChange={(e) => handleEditField('savings_balance', Number(e.target.value))} className="h-7 text-sm mt-1" />
              ) : (
                <p className="font-semibold">{formatCurrency(Number(profile.savings_balance))}</p>
              )}
            </div>
            <div className="rounded-lg bg-muted/50 p-3">
              <p className="text-muted-foreground text-xs">Checking Balance</p>
              {editing ? (
                <Input type="number" step="0.01" value={editData.checking_balance ?? 0} onChange={(e) => handleEditField('checking_balance', Number(e.target.value))} className="h-7 text-sm mt-1" />
              ) : (
                <p className="font-semibold">{formatCurrency(Number(profile.checking_balance))}</p>
              )}
            </div>
            <div className="rounded-lg bg-muted/50 p-3">
              <p className="text-muted-foreground text-xs">Total Deposits</p>
              <p className="font-semibold">
                {editing
                  ? formatCurrency((editData.savings_balance ?? 0) + (editData.checking_balance ?? 0))
                  : formatCurrency(Number(profile.savings_balance) + Number(profile.checking_balance))
                }
              </p>
            </div>
          </div>

          {editing ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-4 text-sm">
              <div className="rounded-lg bg-muted/50 p-3">
                <p className="text-muted-foreground text-xs mb-1">Loyalty Tier</p>
                <Select
                  value={editData.loyalty_tier ?? ''}
                  onChange={(e) => handleEditField('loyalty_tier', e.target.value)}
                  className="h-7 text-sm"
                >
                  <SelectItem value="standard">Standard</SelectItem>
                  <SelectItem value="silver">Silver</SelectItem>
                  <SelectItem value="gold">Gold</SelectItem>
                  <SelectItem value="platinum">Platinum</SelectItem>
                </Select>
              </div>
            </div>
          ) : null}

          <div className="flex flex-wrap gap-4 mt-4">
            <EditableBool value={profile.has_credit_card} label="Credit Card" field="has_credit_card" editing={editing} editData={editData} onChange={handleEditField} />
            <EditableBool value={profile.has_mortgage} label="Mortgage" field="has_mortgage" editing={editing} editData={editData} onChange={handleEditField} />
            <EditableBool value={profile.has_auto_loan} label="Auto Loan" field="has_auto_loan" editing={editing} editData={editData} onChange={handleEditField} />
          </div>
        </CardContent>
      </Card>

      {/* Personal Details + Living Situation — side by side */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <UserCircle className="h-5 w-5 text-muted-foreground" />
              <CardTitle className="text-base">Personal Details</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <EditableField label="Date of Birth" value={profile.date_of_birth ? formatDate(profile.date_of_birth) : null} field="date_of_birth" editing={editing} editData={editData} onChange={handleEditField} type="date" />
            <EditableSelect label="Marital Status" value={profile.marital_status} displayValue={maritalLabels[profile.marital_status] || profile.marital_status} field="marital_status" editing={editing} editData={editData} onChange={handleEditField} options={maritalLabels} />
            <EditableField label="Phone" value={profile.phone} field="phone" editing={editing} editData={editData} onChange={handleEditField} />
            {editing ? (
              <>
                <EditableField label="Address Line 1" value={profile.address_line_1} field="address_line_1" editing={editing} editData={editData} onChange={handleEditField} />
                <EditableField label="Address Line 2" value={profile.address_line_2} field="address_line_2" editing={editing} editData={editData} onChange={handleEditField} />
                <EditableField label="Suburb" value={profile.suburb} field="suburb" editing={editing} editData={editData} onChange={handleEditField} />
                <EditableField label="State" value={profile.state} field="state" editing={editing} editData={editData} onChange={handleEditField} />
                <EditableField label="Postcode" value={profile.postcode} field="postcode" editing={editing} editData={editData} onChange={handleEditField} />
              </>
            ) : fullAddress ? (
              <div className="flex justify-between gap-4">
                <span className="text-muted-foreground shrink-0">Address</span>
                <span className="text-right">{fullAddress}</span>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <div className="flex flex-col gap-6">
          {/* Living Situation */}
          <Card className="flex-1">
            <CardHeader>
              <div className="flex items-center gap-2">
                <UserCircle className="h-5 w-5 text-muted-foreground" />
                <CardTitle className="text-base">Living Situation</CardTitle>
              </div>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <EditableSelect label="Housing Situation" value={profile.housing_situation} displayValue={housingSituationLabels[profile.housing_situation] || profile.housing_situation} field="housing_situation" editing={editing} editData={editData} onChange={handleEditField} options={housingSituationLabels} />
              <EditableField label="Time at Current Address (Years)" value={profile.time_at_current_address_years} field="time_at_current_address_years" editing={editing} editData={editData} onChange={handleEditField} type="number" />
              <EditableField label="Number of Dependants" value={profile.number_of_dependants} field="number_of_dependants" editing={editing} editData={editData} onChange={handleEditField} type="number" />
              {editing ? (
                <>
                  <EditableField label="Previous Suburb" value={profile.previous_suburb} field="previous_suburb" editing={editing} editData={editData} onChange={handleEditField} />
                  <EditableField label="Previous State" value={profile.previous_state} field="previous_state" editing={editing} editData={editData} onChange={handleEditField} />
                  <EditableField label="Previous Postcode" value={profile.previous_postcode} field="previous_postcode" editing={editing} editData={editData} onChange={handleEditField} />
                </>
              ) : (
                (() => {
                  const prevAddress = [profile.previous_suburb, profile.previous_state, profile.previous_postcode].filter(Boolean).join(', ')
                  return prevAddress ? (
                    <div className="flex justify-between gap-4">
                      <span className="text-muted-foreground shrink-0">Previous Address</span>
                      <span className="text-right">{prevAddress}</span>
                    </div>
                  ) : null
                })()
              )}
              <EditableSelect label="Preferred Contact Method" value={profile.preferred_contact_method} displayValue={contactMethodLabels[profile.preferred_contact_method] || profile.preferred_contact_method} field="preferred_contact_method" editing={editing} editData={editData} onChange={handleEditField} options={contactMethodLabels} />
            </CardContent>
          </Card>

          {/* Identity & Compliance */}
          <Card className="flex-1">
            <CardHeader>
              <div className="flex items-center gap-2">
                <Shield className="h-5 w-5 text-muted-foreground" />
                <CardTitle className="text-base">Identity &amp; Compliance</CardTitle>
              </div>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <EditableSelect label="Residency" value={profile.residency_status} displayValue={residencyLabels[profile.residency_status] || profile.residency_status} field="residency_status" editing={editing} editData={editData} onChange={handleEditField} options={residencyLabels} />
              <EditableSelect label="Primary ID" value={profile.primary_id_type} displayValue={idTypeLabels[profile.primary_id_type] || profile.primary_id_type} field="primary_id_type" editing={editing} editData={editData} onChange={handleEditField} options={idTypeLabels} />
              {editing && (
                <EditableField label="Primary ID Number" value="" field="primary_id_number" editing={editing} editData={editData} onChange={handleEditField} />
              )}
              <EditableSelect label="Secondary ID" value={profile.secondary_id_type} displayValue={idTypeLabels[profile.secondary_id_type] || profile.secondary_id_type} field="secondary_id_type" editing={editing} editData={editData} onChange={handleEditField} options={{...idTypeLabels, '': 'None'}} />
              {editing && (
                <EditableField label="Secondary ID Number" value="" field="secondary_id_number" editing={editing} editData={editData} onChange={handleEditField} />
              )}
              {editing ? (
                <>
                  <EditableBool value={profile.tax_file_number_provided} label="TFN Provided" field="tax_file_number_provided" editing={editing} editData={editData} onChange={handleEditField} />
                  <EditableBool value={profile.is_politically_exposed} label="Politically Exposed Person" field="is_politically_exposed" editing={editing} editData={editData} onChange={handleEditField} />
                </>
              ) : (
                <>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">TFN Provided</span>
                    <span>{profile.tax_file_number_provided ? 'Yes' : 'No'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Politically Exposed</span>
                    <span>{profile.is_politically_exposed ? 'Yes' : 'No'}</span>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Employment & Income */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Building2 className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Employment &amp; Income</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="grid gap-6 md:grid-cols-2">
            <div className="space-y-3">
              <EditableField label="Employer Name" value={profile.employer_name} field="employer_name" editing={editing} editData={editData} onChange={handleEditField} />
              <EditableField label="Occupation" value={profile.occupation} field="occupation" editing={editing} editData={editData} onChange={handleEditField} />
              <EditableSelect label="Industry" value={profile.industry} displayValue={industryLabels[profile.industry] || profile.industry} field="industry" editing={editing} editData={editData} onChange={handleEditField} options={industryLabels} />
              <EditableSelect label="Employment Status" value={profile.employment_status} displayValue={employmentStatusLabels[profile.employment_status] || profile.employment_status} field="employment_status" editing={editing} editData={editData} onChange={handleEditField} options={employmentStatusLabels} />
              <EditableField label="Years in Current Role" value={profile.years_in_current_role} field="years_in_current_role" editing={editing} editData={editData} onChange={handleEditField} type="number" />
              <EditableField label="Previous Employer" value={profile.previous_employer} field="previous_employer" editing={editing} editData={editData} onChange={handleEditField} />
            </div>
            <div className="space-y-3">
              <EditableField label="Gross Annual Income" value={editing ? profile.gross_annual_income : formatCurrency(Number(profile.gross_annual_income))} field="gross_annual_income" editing={editing} editData={editData} onChange={handleEditField} type="number" />
              <EditableField label="Other Income" value={editing ? profile.other_income : formatCurrency(Number(profile.other_income))} field="other_income" editing={editing} editData={editData} onChange={handleEditField} type="number" />
              <EditableField label="Other Income Source" value={profile.other_income_source} field="other_income_source" editing={editing} editData={editData} onChange={handleEditField} />
              <EditableField label="Partner Annual Income" value={editing ? profile.partner_annual_income : formatCurrency(Number(profile.partner_annual_income))} field="partner_annual_income" editing={editing} editData={editData} onChange={handleEditField} type="number" />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Assets & Liabilities */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <CreditCard className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Assets &amp; Liabilities</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="grid gap-6 md:grid-cols-2">
            <div className="space-y-3">
              <h4 className="font-medium text-muted-foreground">Assets</h4>
              <EditableField label="Estimated Property Value" value={editing ? profile.estimated_property_value : formatCurrency(Number(profile.estimated_property_value))} field="estimated_property_value" editing={editing} editData={editData} onChange={handleEditField} type="number" />
              <EditableField label="Vehicle Value" value={editing ? profile.vehicle_value : formatCurrency(Number(profile.vehicle_value))} field="vehicle_value" editing={editing} editData={editData} onChange={handleEditField} type="number" />
              <EditableField label="Savings (Other Institutions)" value={editing ? profile.savings_other_institutions : formatCurrency(Number(profile.savings_other_institutions))} field="savings_other_institutions" editing={editing} editData={editData} onChange={handleEditField} type="number" />
              <EditableField label="Investment Value" value={editing ? profile.investment_value : formatCurrency(Number(profile.investment_value))} field="investment_value" editing={editing} editData={editData} onChange={handleEditField} type="number" />
              <EditableField label="Superannuation Balance" value={editing ? profile.superannuation_balance : formatCurrency(Number(profile.superannuation_balance))} field="superannuation_balance" editing={editing} editData={editData} onChange={handleEditField} type="number" />
              <div className="flex justify-between pt-2 border-t">
                <span className="font-semibold">Total Assets</span>
                <span className="font-semibold">{formatCurrency(Number(profile.total_assets))}</span>
              </div>
            </div>
            <div className="space-y-3">
              <h4 className="font-medium text-muted-foreground">Liabilities</h4>
              <EditableField label="Other Loan Repayments (Monthly)" value={editing ? profile.other_loan_repayments_monthly : formatCurrency(Number(profile.other_loan_repayments_monthly))} field="other_loan_repayments_monthly" editing={editing} editData={editData} onChange={handleEditField} type="number" />
              <EditableField label="Other Credit Card Limits" value={editing ? profile.other_credit_card_limits : formatCurrency(Number(profile.other_credit_card_limits))} field="other_credit_card_limits" editing={editing} editData={editData} onChange={handleEditField} type="number" />
              <EditableField label="Rent or Board (Monthly)" value={editing ? profile.rent_or_board_monthly : formatCurrency(Number(profile.rent_or_board_monthly))} field="rent_or_board_monthly" editing={editing} editData={editData} onChange={handleEditField} type="number" />
              <div className="flex justify-between pt-2 border-t">
                <span className="font-semibold">Total Monthly Liabilities</span>
                <span className="font-semibold">{formatCurrency(Number(profile.total_monthly_liabilities))}</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Loan Applications */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Building2 className="h-5 w-5 text-muted-foreground" />
              <CardTitle className="text-base">Loan Applications</CardTitle>
            </div>
            <span className="text-sm text-muted-foreground">{loans.length} application{loans.length !== 1 ? 's' : ''}</span>
          </div>
        </CardHeader>
        <CardContent>
          {loansLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : loans.length === 0 ? (
            <p className="text-center text-muted-foreground py-6">No loan applications</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Amount</TableHead>
                  <TableHead>Purpose</TableHead>
                  <TableHead>Credit Score</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Date</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loans.map((loan) => (
                  <TableRow
                    key={loan.id}
                    className="cursor-pointer"
                    onClick={() => router.push(`/dashboard/applications/${loan.id}`)}
                  >
                    <TableCell className="font-mono text-xs">{loan.id.slice(0, 8)}</TableCell>
                    <TableCell className="font-semibold">{formatCurrency(loan.loan_amount)}</TableCell>
                    <TableCell className="capitalize">{loan.purpose}</TableCell>
                    <TableCell>{loan.credit_score}</TableCell>
                    <TableCell>
                      {(() => { const s = getDisplayStatus(loan.status, loan.decision); return (
                        <Badge className={s.color} variant="outline">{s.label}</Badge>
                      ) })()}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{formatDate(loan.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Generated Emails History */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Mail className="h-5 w-5 text-muted-foreground" />
              <CardTitle className="text-base">Generated Emails</CardTitle>
            </div>
            <span className="text-sm text-muted-foreground">{emails.length} email{emails.length !== 1 ? 's' : ''}</span>
          </div>
        </CardHeader>
        <CardContent>
          {activityLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 2 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : emails.length === 0 ? (
            <p className="text-center text-muted-foreground py-6">No generated emails</p>
          ) : (
            <div className="divide-y -mx-6">
              {emails.map((email) => {
                const isOpen = expandedEmail === email.id
                return (
                  <div key={email.id}>
                    <button
                      onClick={() => setExpandedEmail(isOpen ? null : email.id)}
                      className="flex w-full items-center gap-3 px-6 py-3 text-left hover:bg-muted/50 transition-colors"
                    >
                      {isOpen ? (
                        <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
                      ) : (
                        <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{email.subject}</p>
                        <p className="text-xs text-muted-foreground">
                          {formatDate(email.created_at)} &middot; Application {email.application_id.slice(0, 8)}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <Badge variant="outline" className={
                          email.decision === 'approved' ? 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950 dark:text-green-400 dark:border-green-800' :
                          email.decision === 'denied' ? 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950 dark:text-red-400 dark:border-red-800' :
                          email.decision === 'pending' ? 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950 dark:text-amber-400 dark:border-amber-800' :
                          'bg-zinc-50 text-zinc-700 border-zinc-200 dark:bg-zinc-900 dark:text-zinc-400 dark:border-zinc-700'
                        }>
                          {email.decision.toUpperCase()}
                        </Badge>
                        {email.passed_guardrails ? (
                          <CheckCircle className="h-4 w-4 text-green-600" />
                        ) : (
                          <XCircle className="h-4 w-4 text-red-500" />
                        )}
                      </div>
                    </button>
                    {isOpen && (
                      <div className="px-6 pb-4">
                        <EmailPreview email={email} />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Agent Workflow History */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bot className="h-5 w-5 text-muted-foreground" />
              <CardTitle className="text-base">Agent Workflows</CardTitle>
            </div>
            <span className="text-sm text-muted-foreground">{agentRuns.length} workflow{agentRuns.length !== 1 ? 's' : ''}</span>
          </div>
        </CardHeader>
        <CardContent>
          {activityLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 2 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : agentRuns.length === 0 ? (
            <p className="text-center text-muted-foreground py-6">No agent workflows</p>
          ) : (
            <div className="divide-y -mx-6">
              {agentRuns.map((run) => {
                const isOpen = expandedRun === run.id
                return (
                  <div key={run.id}>
                    <button
                      onClick={() => setExpandedRun(isOpen ? null : run.id)}
                      className="flex w-full items-center gap-3 px-6 py-3 text-left hover:bg-muted/50 transition-colors"
                    >
                      {isOpen ? (
                        <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
                      ) : (
                        <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium">
                          Application {run.application_id.slice(0, 8)}
                          {run.steps.length > 0 && ` · ${run.steps.length} steps`}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {formatDate(run.created_at)}
                          {run.total_time_ms && ` · ${(run.total_time_ms / 1000).toFixed(1)}s`}
                        </p>
                      </div>
                      <Badge className={getStatusColor(run.status)} variant="outline">
                        {run.status.toUpperCase()}
                      </Badge>
                    </button>
                    {isOpen && (
                      <div className="px-6 pb-4 space-y-4">
                        {run.steps.length > 0 && (
                          <div>
                            <h4 className="text-sm font-medium mb-3">Workflow Steps</h4>
                            <WorkflowTimeline steps={run.steps} />
                          </div>
                        )}
                        {run.steps.length > 0 && (
                          <div className="space-y-2">
                            <h4 className="text-sm font-medium">Step Details</h4>
                            {run.steps.map((step, index) => (
                              <AgentStepCard key={index} step={step} />
                            ))}
                          </div>
                        )}
                        {run.next_best_offers && run.next_best_offers.length > 0 && (
                          <div className="space-y-2">
                            {run.next_best_offers.map((offer) => (
                              <NextBestOfferCard key={offer.id} offer={offer} />
                            ))}
                          </div>
                        )}
                        {run.marketing_emails && run.marketing_emails.length > 0 && (
                          <div className="space-y-2">
                            {run.marketing_emails.map((email) => (
                              <MarketingEmailCard key={email.id} email={email} />
                            ))}
                          </div>
                        )}
                        {run.error && (
                          <div className="rounded-md bg-destructive/10 p-3">
                            <p className="text-sm text-destructive">{run.error}</p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
