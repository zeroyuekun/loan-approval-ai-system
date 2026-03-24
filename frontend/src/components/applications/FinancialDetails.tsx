'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { LoanApplication } from '@/types'
import { formatCurrency } from '@/lib/utils'

interface FinancialDetailsProps {
  application: LoanApplication
}

export function FinancialDetails({ application }: FinancialDetailsProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Financial Details</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Loan Amount</span>
          <span className="font-semibold">{formatCurrency(application.loan_amount)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Annual Income</span>
          <span>{formatCurrency(application.annual_income)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Credit Score</span>
          <span>{application.credit_score}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Loan Term</span>
          <span>{application.loan_term_months} months</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">DTI Ratio</span>
          <span>{Number(application.debt_to_income).toFixed(1)}x</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Employment</span>
          <span className="capitalize">{application.employment_type?.replace(/_/g, ' ') || '—'} ({application.employment_length} yrs)</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Applicant Type</span>
          <span className="capitalize">{application.applicant_type} ({application.number_of_dependants} dependants)</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Monthly Expenses</span>
          <span>{application.monthly_expenses != null ? formatCurrency(application.monthly_expenses) : '—'}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Credit Card Limit</span>
          <span>{formatCurrency(application.existing_credit_card_limit)}</span>
        </div>
        {application.purpose === 'home' && application.property_value != null && (
          <>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Property Value</span>
              <span>{formatCurrency(application.property_value)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Deposit</span>
              <span>{application.deposit_amount != null ? formatCurrency(application.deposit_amount) : '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">LVR</span>
              <span>{application.property_value > 0 ? `${((application.loan_amount / application.property_value) * 100).toFixed(1)}%` : '—'}</span>
            </div>
          </>
        )}
        <div className="flex justify-between">
          <span className="text-muted-foreground">Home Ownership</span>
          <span className="capitalize">{application.home_ownership}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Co-signer</span>
          <span>{application.has_cosigner ? 'Yes' : 'No'}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">HECS/HELP Debt</span>
          <span>{application.has_hecs ? 'Yes' : 'No'}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Bankruptcy History</span>
          <span>{application.has_bankruptcy ? 'Yes' : 'No'}</span>
        </div>
      </CardContent>
    </Card>
  )
}
