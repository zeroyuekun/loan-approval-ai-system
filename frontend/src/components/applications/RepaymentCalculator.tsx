'use client'

import { useState, useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Calculator, TrendingUp } from 'lucide-react'
import { cn, formatCurrency } from '@/lib/utils'
import { ComparisonRate } from '@/components/finance/ComparisonRate'

interface RepaymentCalculatorProps {
  loanAmount?: number
  loanTermMonths?: number
  /** Annual interest rate as a percentage (e.g. 6.5) */
  interestRate?: number
}

/**
 * Calculate monthly P&I repayment.
 * Formula: M = P * r * (1+r)^n / ((1+r)^n - 1)
 * where P = principal, r = monthly rate, n = number of months
 */
function calculateMonthlyRepayment(principal: number, annualRate: number, months: number): number {
  if (principal <= 0 || months <= 0) return 0
  if (annualRate <= 0) return principal / months

  const monthlyRate = annualRate / 100 / 12
  const factor = Math.pow(1 + monthlyRate, months)
  return (principal * monthlyRate * factor) / (factor - 1)
}

/**
 * Calculate comparison rate per National Credit Code Schedule 6.
 * Reference loan: $150,000 over 25 years (secured personal credit).
 * Comparison rate includes standard fees to give a truer cost of credit.
 */
function calculateComparisonRate(
  annualRate: number,
  establishmentFee: number = 250,
  monthlyFee: number = 10,
): number {
  const refPrincipal = 150000
  const refMonths = 300 // 25 years
  const totalBorrowed = refPrincipal - establishmentFee // net proceeds
  // Solve for the rate that makes net proceeds = PV of all payments
  // Using iterative Newton-Raphson method
  let guess = annualRate / 100 / 12 // monthly rate guess
  for (let i = 0; i < 100; i++) {
    const r = guess
    if (r <= 0) { guess = 0.001; continue }
    const factor = Math.pow(1 + r, refMonths)
    const basePayment = (refPrincipal * r * factor) / (factor - 1)
    const totalPayment = basePayment + monthlyFee
    // PV of all payments at rate r
    const pv = totalPayment * (factor - 1) / (r * factor)
    const f = pv - totalBorrowed
    // Derivative of PV w.r.t. r (numerical approximation)
    const dr = 0.00001
    const r2 = r + dr
    const factor2 = Math.pow(1 + r2, refMonths)
    const basePayment2 = (refPrincipal * r2 * factor2) / (factor2 - 1)
    const totalPayment2 = basePayment2 + monthlyFee
    const pv2 = totalPayment2 * (factor2 - 1) / (r2 * factor2)
    const fprime = (pv2 - totalBorrowed - f) / dr
    if (Math.abs(fprime) < 1e-12) break
    guess = r - f / fprime
    if (Math.abs(f) < 0.01) break
  }
  return guess * 12 * 100 // Convert back to annual percentage
}

export function RepaymentCalculator({
  loanAmount = 300000,
  loanTermMonths = 360,
  interestRate = 6.5,
}: RepaymentCalculatorProps) {
  const [stressBuffer, setStressBuffer] = useState(0)

  const effectiveRate = interestRate + stressBuffer

  const results = useMemo(() => {
    const monthly = calculateMonthlyRepayment(loanAmount, effectiveRate, loanTermMonths)
    const totalRepayment = monthly * loanTermMonths
    const totalInterest = totalRepayment - loanAmount

    return { monthly, totalRepayment, totalInterest }
  }, [loanAmount, effectiveRate, loanTermMonths])

  const baseResults = useMemo(() => {
    const monthly = calculateMonthlyRepayment(loanAmount, interestRate, loanTermMonths)
    return { monthly }
  }, [loanAmount, interestRate, loanTermMonths])

  const stressIncrease = results.monthly - baseResults.monthly

  const comparisonRate = useMemo(
    () => calculateComparisonRate(effectiveRate),
    [effectiveRate],
  )

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Calculator className="h-4 w-4 text-blue-600" />
          Repayment Estimator
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className="text-xs text-muted-foreground">Loan Amount</p>
            <p className="font-semibold text-sm">{formatCurrency(loanAmount)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Term</p>
            <p className="font-semibold text-sm">{loanTermMonths} months</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Rate</p>
            <p className="font-semibold text-sm">{effectiveRate.toFixed(2)}% p.a.</p>
            <p className="text-xs text-muted-foreground">
              Comparison {comparisonRate.toFixed(2)}% p.a.
            </p>
          </div>
        </div>

        {/* Stress test buttons */}
        <div className="space-y-2">
          <div className="flex items-center gap-1.5">
            <TrendingUp className="h-3.5 w-3.5 text-amber-600" />
            <span className="text-xs font-medium">Interest Rate Stress Test</span>
          </div>
          <div className="flex gap-2">
            {[0, 1, 2, 3].map((buffer) => (
              <Button
                key={buffer}
                variant="outline"
                size="sm"
                className={cn(
                  "flex-1 text-xs",
                  stressBuffer === buffer && "bg-amber-50 border-amber-300 text-amber-800"
                )}
                onClick={() => setStressBuffer(buffer)}
                aria-pressed={stressBuffer === buffer}
                aria-label={buffer === 0 ? 'Base rate' : `Plus ${buffer} percent stress test`}
              >
                {buffer === 0 ? 'Base' : `+${buffer}%`}
              </Button>
            ))}
          </div>
          <p className="text-[11px] text-muted-foreground">
            APRA serviceability: lenders must assess at a buffer of at least +3% above the product rate.
          </p>
        </div>

        {/* Results */}
        <div className="rounded-lg bg-muted p-4 space-y-2">
          <div className="flex justify-between items-baseline">
            <span className="text-sm">Monthly Repayment</span>
            <span className="text-lg font-bold">{formatCurrency(results.monthly)}</span>
          </div>
          {stressBuffer > 0 && (
            <div className="flex justify-between items-baseline text-amber-600">
              <span className="text-xs">Increase from stress test</span>
              <span className="text-sm font-medium">+{formatCurrency(stressIncrease)}/mo</span>
            </div>
          )}
          <div className="flex justify-between items-baseline pt-1 border-t border-border/50">
            <span className="text-xs text-muted-foreground">Total Interest</span>
            <span className="text-sm text-muted-foreground">{formatCurrency(results.totalInterest)}</span>
          </div>
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-muted-foreground">Total Repayment</span>
            <span className="text-sm text-muted-foreground">{formatCurrency(results.totalRepayment)}</span>
          </div>
        </div>

        {/*
          NCCP Sch 1 comparison-rate surface. RepaymentCalculator stores
          rates as percentages (e.g. 6.25); ComparisonRate expects fractions.
        */}
        <ComparisonRate
          headlineRate={effectiveRate / 100}
          comparisonRate={comparisonRate / 100}
          loanAmount={loanAmount}
          termYears={Math.round(loanTermMonths / 12)}
        />

        <p className="text-[11px] text-muted-foreground leading-relaxed">
          This estimate is indicative only and does not constitute a loan offer. Actual
          repayments may vary based on the approved rate, fees, and loan structure. Figures
          assume principal and interest repayments over the full loan term.
        </p>
      </CardContent>
    </Card>
  )
}
