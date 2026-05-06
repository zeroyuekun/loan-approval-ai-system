'use client'

import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/lib/auth'
import { authApi } from '@/lib/api'
import { useApplications } from '@/hooks/useApplications'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { getDisplayStatus, formatCurrency, formatDate, formatPurpose } from '@/lib/utils'
import { Plus, ArrowRight, AlertTriangle } from 'lucide-react'
import Link from 'next/link'
import { CustomerProfile } from '@/types'

const FIELD_LABELS: Record<string, string> = {
  date_of_birth: 'Date of birth',
  phone: 'Phone number',
  address_line_1: 'Street address',
  suburb: 'Suburb',
  state: 'State',
  postcode: 'Postcode',
  residency_status: 'Residency status',
  primary_id_type: 'Primary ID type',
  primary_id_number: 'Primary ID number',
}

export default function CustomerApplyPage() {
  const { user } = useAuth()
  const { data, isLoading } = useApplications()

  const { data: profile, isLoading: profileLoading } = useQuery<CustomerProfile>({
    queryKey: ['customerProfile'],
    queryFn: async () => {
      const { data } = await authApi.getCustomerProfile()
      return data
    },
  })

  const profileComplete = profile?.is_profile_complete ?? false
  const applications = data?.results || []


  const ProfileBanner = () => {
    if (profileLoading || profileComplete) return null
    const missing = profile?.missing_profile_fields || []
    return (
      <Card className="border-amber-300 bg-amber-50">
        <CardContent className="flex items-start gap-4 py-5">
          <AlertTriangle className="h-6 w-6 text-amber-600 mt-0.5 shrink-0" />
          <div className="space-y-2">
            <p className="font-semibold text-amber-900">Complete your profile to apply</p>
            <p className="text-sm text-amber-800">
              Under Australian lending regulations (NCCP Act 2009 and AML/CTF Act 2006),
              we need your personal details and identity documents before you can submit a loan application.
            </p>
            {missing.length > 0 && (
              <p className="text-sm text-amber-700">
                Missing: {missing.map(f => FIELD_LABELS[f] || f.replace(/_/g, ' ')).join(', ')}
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">
          Welcome{user?.first_name ? `, ${user.first_name}` : ''}
        </h2>
        <p className="text-muted-foreground mt-1">
          Apply for a loan or check the status of your existing applications.
        </p>
      </div>

      <ProfileBanner />

      {isLoading || profileLoading ? (
        <div className="space-y-4">
          {[1, 2].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      ) : applications.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <p className="text-lg font-medium mb-2">No Applications Yet</p>
            <p className="text-muted-foreground mb-6">
              {profileComplete
                ? 'Submit your first loan application to get started.'
                : 'Complete your profile to submit your first loan application.'}
            </p>
            {profileComplete ? (
              <Link href="/apply/new">
                <Button>
                  <Plus className="mr-2 h-4 w-4" />
                  Apply Now
                </Button>
              </Link>
            ) : (
              <Link href="/apply/profile">
                <Button>Complete Profile</Button>
              </Link>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold">Your Applications</h3>
            <Link href={profileComplete ? '/apply/new' : '/apply/profile'}>
              <Button size="sm">
                Apply Now
              </Button>
            </Link>
          </div>
          <div className="space-y-3">
          {applications.map((app) => (
            <Link key={app.id} href={`/apply/status/${app.id}`}>
              <Card className="hover:bg-accent/50 transition-colors cursor-pointer">
                <CardContent className="flex items-center justify-between py-4">
                  <div className="flex items-center gap-6">
                    <div>
                      <p className="font-medium">{formatPurpose(app.purpose)} Loan</p>
                      <p className="text-sm text-muted-foreground">
                        {formatDate(app.created_at)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="font-semibold">{formatCurrency(app.loan_amount)}</p>
                      <p className="text-sm text-muted-foreground">
                        {app.loan_term_months} months
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {(() => { const s = getDisplayStatus(app.status, app.decision); return (
                      <Badge className={s.color} variant="outline">{s.label}</Badge>
                    ) })()}
                    <ArrowRight className="h-4 w-4 text-muted-foreground" />
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
          </div>
        </div>
      )}

      <div className="pt-4 border-t text-center">
        <Link href="/rights" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
          Your rights as a borrower
        </Link>
      </div>
    </div>
  )
}
