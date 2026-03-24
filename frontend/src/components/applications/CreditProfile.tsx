'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { LoanApplication } from '@/types'

interface CreditProfileProps {
  application: LoanApplication
}

export function CreditProfile({ application }: CreditProfileProps) {
  const shouldRender = application.credit_utilization_pct != null || application.stress_index != null || application.actual_outcome

  if (!shouldRender) return null

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">Credit Profile</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          {application.credit_utilization_pct != null && (
            <div>
              <p className="text-muted-foreground">Credit Utilization</p>
              <p className={`font-medium ${(application.credit_utilization_pct ?? 0) > 0.6 ? 'text-red-600' : (application.credit_utilization_pct ?? 0) > 0.3 ? 'text-amber-600' : 'text-green-600'}`}>
                {((application.credit_utilization_pct ?? 0) * 100).toFixed(0)}%
              </p>
            </div>
          )}
          {application.num_late_payments_24m != null && (
            <div>
              <p className="text-muted-foreground">Late Payments (24m)</p>
              <p className="font-medium">{application.num_late_payments_24m}</p>
            </div>
          )}
          {application.stress_index != null && (
            <div>
              <p className="text-muted-foreground">Stress Index</p>
              <p className={`font-medium ${(application.stress_index ?? 0) > 60 ? 'text-red-600' : (application.stress_index ?? 0) > 30 ? 'text-amber-600' : 'text-green-600'}`}>
                {(application.stress_index ?? 0).toFixed(0)}/100
              </p>
            </div>
          )}
          {application.debt_service_coverage != null && (
            <div>
              <p className="text-muted-foreground">Debt Service Coverage</p>
              <p className={`font-medium ${(application.debt_service_coverage ?? 0) < 1.0 ? 'text-red-600' : (application.debt_service_coverage ?? 0) < 1.25 ? 'text-amber-600' : 'text-green-600'}`}>
                {(application.debt_service_coverage ?? 0).toFixed(2)}x
              </p>
            </div>
          )}
          {application.bnpl_active_count != null && application.bnpl_active_count > 0 && (
            <div>
              <p className="text-muted-foreground">BNPL Accounts</p>
              <p className="font-medium">{application.bnpl_active_count}</p>
            </div>
          )}
          {application.salary_credit_regularity != null && (
            <div>
              <p className="text-muted-foreground">Salary Regularity</p>
              <p className="font-medium">{((application.salary_credit_regularity ?? 0) * 100).toFixed(0)}%</p>
            </div>
          )}
          {application.hem_surplus != null && (
            <div>
              <p className="text-muted-foreground">HEM Surplus</p>
              <p className={`font-medium ${(application.hem_surplus ?? 0) < 0 ? 'text-red-600' : 'text-green-600'}`}>
                ${Math.round(application.hem_surplus ?? 0).toLocaleString()}
              </p>
            </div>
          )}
          {application.actual_outcome && (
            <div>
              <p className="text-muted-foreground">Outcome</p>
              <Badge variant="outline" className={application.actual_outcome === 'performing' ? 'bg-green-100 text-green-800' : application.actual_outcome === 'default' ? 'bg-red-100 text-red-800' : ''}>
                {application.actual_outcome.replace('_', ' ')}
              </Badge>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
