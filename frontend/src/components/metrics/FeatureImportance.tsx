'use client'

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useChartHover, ChartHoverPanel, renderEmptyTooltip } from './ChartHoverPanel'

interface FeatureImportanceProps {
  features: Record<string, number> | Array<{ feature: string; importance: number }>
  title?: string
}

const FEATURE_LABELS: Record<string, string> = {
    // Interactions
    lvr_x_dti: 'LVR × DTI',
    lvr_x_property_growth: 'LVR × Property Growth',
    credit_score_x_tenure: 'Credit Score × Tenure',
    deposit_x_income_stability: 'Deposit × Income Stability',
    dti_x_rate_sensitivity: 'DTI × Rate Sensitivity',
    credit_x_employment: 'Credit × Employment',
    income_credit_interaction: 'Income × Credit',
    // Affordability
    debt_service_coverage: 'Debt Service Coverage',
    stressed_dsr: 'Stressed DSR',
    net_monthly_surplus: 'Net Monthly Surplus',
    monthly_repayment_ratio: 'Monthly Repayment Ratio',
    uncommitted_monthly_income: 'Uncommitted Monthly Income',
    hem_surplus: 'HEM Surplus',
    rate_stress_buffer: 'Rate Stress Buffer',
    stressed_repayment: 'Stressed Repayment',
    stress_index: 'Stress Index',
    debt_to_income: 'Debt-to-Income',
    loan_to_income: 'Loan-to-Income',
    expense_to_income: 'Expense-to-Income',
    serviceability_ratio: 'Serviceability Ratio',
    // Credit
    credit_score: 'Credit Score',
    credit_utilization_pct: 'Credit Utilisation %',
    credit_history_months: 'Credit History (Months)',
    num_credit_enquiries_6m: 'Credit Enquiries (6m)',
    num_defaults_5yr: 'Defaults (5yr)',
    worst_late_payment_days: 'Worst Late Payment (Days)',
    cash_advance_count_12m: 'Cash Advances (12m)',
    bureau_risk_score: 'Bureau Risk Score',
    // Loan structure
    lvr: 'LVR',
    deposit_ratio: 'Deposit Ratio',
    deposit_amount: 'Deposit Amount',
    loan_amount: 'Loan Amount',
    log_loan_amount: 'Log Loan Amount',
    loan_term_months: 'Loan Term (Months)',
    savings_to_loan_ratio: 'Savings-to-Loan Ratio',
    property_value: 'Property Value',
    // Employment
    employment_length: 'Employment Length',
    employment_stability: 'Employment Stability',
    employment_type_payg_permanent: 'Employment: PAYG Permanent',
    employment_type_payg_casual: 'Employment: PAYG Casual',
    employment_type_self_employed: 'Employment: Self-Employed',
    employment_type_contract: 'Employment: Contract',
    // Personal
    annual_income: 'Annual Income',
    has_bankruptcy: 'Has Bankruptcy',
    has_cosigner: 'Has Co-signer',
    has_hecs: 'Has HECS',
    number_of_dependants: 'Number of Dependants',
    existing_property_count: 'Existing Property Count',
    // Categories
    applicant_type_single: 'Applicant: Single',
    applicant_type_couple: 'Applicant: Couple',
    home_ownership_own: 'Ownership: Own',
    home_ownership_rent: 'Ownership: Rent',
    home_ownership_mortgage: 'Ownership: Mortgage',
    purpose_home: 'Purpose: Home',
    purpose_auto: 'Purpose: Auto',
    purpose_personal: 'Purpose: Personal',
    purpose_business: 'Purpose: Business',
    purpose_education: 'Purpose: Education',
    // Savings
    savings_trend_3m_positive: 'Savings Trend: Positive',
    savings_trend_3m_negative: 'Savings Trend: Negative',
    savings_trend_3m_flat: 'Savings Trend: Flat',
    // Geography
    state_nsw: 'State: NSW',
    state_vic: 'State: VIC',
    state_qld: 'State: QLD',
    state_wa: 'State: WA',
    state_sa: 'State: SA',
    state_tas: 'State: TAS',
    state_act: 'State: ACT',
    state_nt: 'State: NT',
    // Industry
    industry_anzsic_a: 'Industry: Agriculture',
    industry_anzsic_b: 'Industry: Mining',
    industry_anzsic_c: 'Industry: Manufacturing',
    industry_anzsic_e: 'Industry: Construction',
    industry_anzsic_g: 'Industry: Retail',
    industry_anzsic_h: 'Industry: Accommodation',
    industry_anzsic_i: 'Industry: Transport',
    industry_anzsic_j: 'Industry: IT & Media',
    industry_anzsic_k: 'Industry: Finance',
    industry_anzsic_m: 'Industry: Professional Services',
    industry_anzsic_n: 'Industry: Admin Services',
    industry_anzsic_o: 'Industry: Public Admin',
    industry_anzsic_p: 'Industry: Education',
    industry_anzsic_q: 'Industry: Health Care',
    industry_anzsic_s: 'Industry: Other Services',
    industry_risk_tier_low: 'Industry Risk: Low',
    industry_risk_tier_medium: 'Industry Risk: Medium',
    industry_risk_tier_high: 'Industry Risk: High',
    industry_risk_tier_very_high: 'Industry Risk: Very High',
}

// One-hot dummy prefix → parent categorical label. Mirrors
// ModelTrainer.CATEGORICAL_COLS in
// backend/apps/ml_engine/services/training/trainer.py — keep in sync if a
// categorical is added there. An unmatched categorical degrades gracefully
// (renders as individual dummy bars); it is never silently wrong.
const CATEGORY_GROUPS: Record<string, string> = {
  state_: 'State',
  industry_anzsic_: 'Industry (ANZSIC)',
  industry_risk_tier_: 'Industry Risk Tier',
  purpose_: 'Loan Purpose',
  home_ownership_: 'Home Ownership',
  employment_type_: 'Employment Type',
  applicant_type_: 'Applicant Type',
  savings_trend_3m_: 'Savings Trend (3m)',
}
// Match the most specific (longest) prefix first.
const CATEGORY_PREFIXES = Object.keys(CATEGORY_GROUPS).sort((a, b) => b.length - a.length)

const TOP_N = 20

function formatFeatureName(s: string): string {
  return FEATURE_LABELS[s] ?? s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function parentLabelFor(rawKey: string): string | null {
  for (const prefix of CATEGORY_PREFIXES) {
    if (rawKey.startsWith(prefix)) return CATEGORY_GROUPS[prefix]
  }
  return null
}

function toEntries(
  features: Record<string, number> | Array<{ feature: string; importance: number }>,
): Array<{ feature: string; importance: number }> {
  if (Array.isArray(features)) {
    return features.filter(
      (f): f is { feature: string; importance: number } =>
        f != null && typeof f === 'object' && 'feature' in f && 'importance' in f,
    )
  }
  return Object.entries(features).map(([feature, importance]) => ({ feature, importance: Number(importance) }))
}

export interface FeatureBar {
  name: string
  importance: number
  isOther?: boolean
}

export interface FeatureImportanceModel {
  charted: FeatureBar[]
  unusedCount: number
  total: number
}

/**
 * Collapse one-hot dummies into parent categoricals, then split into the
 * charted set (importance > 0, sorted desc) and a count of unused features
 * (importance rounds to 0 — the model never split on them).
 */
export function buildFeatureImportanceModel(
  features: Record<string, number> | Array<{ feature: string; importance: number }>,
): FeatureImportanceModel {
  const groups = new Map<string, number>()
  for (const { feature, importance } of toEntries(features)) {
    const imp = Number(importance)
    if (!Number.isFinite(imp)) continue
    const label = parentLabelFor(feature) ?? formatFeatureName(feature)
    groups.set(label, (groups.get(label) ?? 0) + imp)
  }
  const grouped: FeatureBar[] = Array.from(groups.entries()).map(([name, importance]) => ({ name, importance }))
  const charted = grouped.filter((d) => d.importance > 0).sort((a, b) => b.importance - a.importance)
  return { charted, unusedCount: grouped.length - charted.length, total: charted.length }
}

/** Collapsed view = top N + an "Other (k features)" rollup; expanded = full charted set. */
export function selectShownBars(charted: FeatureBar[], expanded: boolean, topN: number = TOP_N): FeatureBar[] {
  if (expanded || charted.length <= topN) return charted
  const tail = charted.slice(topN)
  const otherSum = tail.reduce((acc, d) => acc + d.importance, 0)
  return [
    ...charted.slice(0, topN),
    { name: `Other (${tail.length} feature${tail.length === 1 ? '' : 's'})`, importance: otherSum, isOther: true },
  ]
}

export function FeatureImportance({ features, title = 'Feature Importance' }: FeatureImportanceProps) {
  const { active, hoverProps } = useChartHover()

  const data = (Array.isArray(features)
    ? features
        .filter((f): f is { feature: string; importance: number } =>
          f != null && typeof f === 'object' && 'feature' in f && 'importance' in f
        )
        .map((f) => ({ name: formatFeatureName(f.feature), importance: f.importance }))
    : Object.entries(features).map(([name, importance]) => ({
        name: formatFeatureName(name),
        importance: Number(importance),
      }))
  )
    .filter((d) => Number.isFinite(d.importance) && d.importance > 0)
    .sort((a, b) => b.importance - a.importance)

  const TOP_N = 15
  const hiddenCount = Math.max(0, data.length - TOP_N)
  const shown = data.slice(0, TOP_N)

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="sr-only" aria-label="Feature importance list">
          {shown.map((d) => (
            <li key={d.name}>{d.name}</li>
          ))}
        </ul>
        <div role="img" aria-label={`Bar chart of top ${shown.length} features by importance: ${shown.slice(0, 3).map((d) => `${d.name} ${(d.importance * 100).toFixed(1)}%`).join(', ')}`}>
        <ResponsiveContainer width="100%" height={Math.max(280, shown.length * 36)}>
          <BarChart data={shown} layout="vertical" margin={{ top: 5, right: 30, bottom: 5, left: 10 }} {...hoverProps}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.4} horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 11 }} tickLine={{ stroke: '#d1d5db' }} />
            <YAxis
              dataKey="name"
              type="category"
              tick={{ fontSize: 11 }}
              width={160}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip content={renderEmptyTooltip} />
            <Bar dataKey="importance" name="Importance" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
        </div>
        <ChartHoverPanel active={active} formatValue={(v) => `${(Number(v) * 100).toFixed(1)}%`} />
        {hiddenCount > 0 && (
          <p className="mt-2 text-center text-xs text-muted-foreground">
            +{hiddenCount} more feature{hiddenCount === 1 ? '' : 's'} not shown
          </p>
        )}
      </CardContent>
    </Card>
  )
}
