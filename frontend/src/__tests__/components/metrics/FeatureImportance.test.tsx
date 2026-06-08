import { render, screen, fireEvent } from '@testing-library/react'
import {
  FeatureImportance,
  buildFeatureImportanceModel,
  selectShownBars,
} from '@/components/metrics/FeatureImportance'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock as any

describe('buildFeatureImportanceModel', () => {
  it('collapses one-hot dummies into a single parent bar (summed)', () => {
    const model = buildFeatureImportanceModel({
      state_nsw: 0.05,
      state_vic: 0.03,
      state_qld: 0.02,
      credit_score: 0.4,
    })
    const state = model.charted.find((b) => b.name === 'State')
    expect(state).toBeDefined()
    expect(state!.importance).toBeCloseTo(0.1, 6)
    expect(model.charted.some((b) => b.name === 'State: NSW')).toBe(false)
  })

  it('does not capture numeric look-alikes into a categorical group', () => {
    const model = buildFeatureImportanceModel({
      employment_length: 0.2,
      employment_stability: 0.1,
      employment_type_payg_permanent: 0.05,
      savings_balance: 0.15,
      savings_to_loan_ratio: 0.07,
      savings_trend_3m_positive: 0.04,
    })
    const names = model.charted.map((b) => b.name)
    expect(names).toContain('Employment Length')
    expect(names).toContain('Employment Stability')
    expect(names).toContain('Savings Balance')
    expect(names).toContain('Savings-to-Loan Ratio')
    expect(names).toContain('Employment Type')
    expect(names).toContain('Savings Trend (3m)')
    const empType = model.charted.find((b) => b.name === 'Employment Type')
    expect(empType!.importance).toBeCloseTo(0.05, 6)
  })

  it('counts zero-importance (unused) features instead of charting them', () => {
    const model = buildFeatureImportanceModel({
      credit_score: 0.5,
      annual_income: 0.3,
      monthly_rent: 0,
      applicant_type_single: 0,
      applicant_type_couple: 0,
    })
    expect(model.charted.map((b) => b.name)).toEqual(['Credit Score', 'Annual Income'])
    expect(model.unusedCount).toBe(2)
    expect(model.total).toBe(2)
  })

  it('groups array input identically to record input', () => {
    const record = buildFeatureImportanceModel({ state_nsw: 0.05, state_vic: 0.05, credit_score: 0.4 })
    const array = buildFeatureImportanceModel([
      { feature: 'state_nsw', importance: 0.05 },
      { feature: 'state_vic', importance: 0.05 },
      { feature: 'credit_score', importance: 0.4 },
    ])
    expect(array.charted).toEqual(record.charted)
  })
})

describe('selectShownBars', () => {
  function rankedFeatures(n: number): Record<string, number> {
    const out: Record<string, number> = {}
    for (let i = 0; i < n; i++) out[`feat_${i}`] = (n - i) / n
    return out
  }

  it('rolls the tail into an "Other" bar that conserves the tail sum', () => {
    const { charted } = buildFeatureImportanceModel(rankedFeatures(25))
    const shown = selectShownBars(charted, false)
    expect(shown).toHaveLength(21)
    const other = shown[shown.length - 1]
    expect(other.isOther).toBe(true)
    expect(other.name).toBe('Other (5 features)')
    const tailSum = charted.slice(20).reduce((a, b) => a + b.importance, 0)
    expect(other.importance).toBeCloseTo(tailSum, 6)
  })

  it('counts grouped units in "Other", not raw dummy columns', () => {
    const features: Record<string, number> = {}
    for (let i = 0; i < 20; i++) features[`feat_${i}`] = 1 - i * 0.01
    ;['nsw', 'vic', 'qld', 'wa', 'sa', 'tas', 'act', 'nt'].forEach(
      (s, i) => (features[`state_${s}`] = 0.001 * (i + 1)),
    )
    const { charted } = buildFeatureImportanceModel(features)
    expect(charted).toHaveLength(21)
    const shown = selectShownBars(charted, false)
    const other = shown[shown.length - 1]
    expect(other.isOther).toBe(true)
    expect(other.name).toBe('Other (1 feature)')
  })

  it('shows no "Other" bar when 20 or fewer charted features', () => {
    const { charted } = buildFeatureImportanceModel(rankedFeatures(10))
    const shown = selectShownBars(charted, false)
    expect(shown).toHaveLength(10)
    expect(shown.some((b) => b.isOther)).toBe(false)
  })

  it('expanded shows the full charted set with no "Other" bar', () => {
    const { charted } = buildFeatureImportanceModel(rankedFeatures(25))
    const shown = selectShownBars(charted, true)
    expect(shown).toHaveLength(25)
    expect(shown.some((b) => b.isOther)).toBe(false)
  })

  it('realistic mixed shape exceeds 20 grouped features so the rollup is live', () => {
    const features: Record<string, number> = {}
    for (let i = 0; i < 30; i++) features[`num_${i}`] = 1 - i * 0.01
    ;['nsw', 'vic', 'qld'].forEach((s, i) => (features[`state_${s}`] = 0.02 * (i + 1)))
    ;['a', 'b', 'c', 'e', 'g'].forEach((s, i) => (features[`industry_anzsic_${s}`] = 0.01 * (i + 1)))
    const { charted } = buildFeatureImportanceModel(features)
    expect(charted.length).toBe(32)
    expect(charted.length).toBeGreaterThan(20)
    expect(selectShownBars(charted, false).some((b) => b.isOther)).toBe(true)
  })
})

describe('<FeatureImportance />', () => {
  function rankedRecord(n: number): Record<string, number> {
    const out: Record<string, number> = {}
    for (let i = 0; i < n; i++) out[`feat_${i}`] = (n - i) / n
    return out
  }

  it('renders the honest, algorithm-neutral caption', () => {
    render(<FeatureImportance features={{ credit_score: 0.5 }} />)
    expect(screen.getByText(/normalised tree-based importance/i)).toBeInTheDocument()
    expect(screen.getByText(/magnitude only/i)).toBeInTheDocument()
  })

  it('discloses unused (zero-importance) features in the footer', () => {
    render(
      <FeatureImportance features={{ credit_score: 0.6, annual_income: 0.4, monthly_rent: 0, hem_gap: 0 }} />,
    )
    expect(screen.getByText(/2 features had no measurable contribution/i)).toBeInTheDocument()
  })

  it('omits the footer disclosure when every feature is used', () => {
    render(<FeatureImportance features={{ credit_score: 0.6, annual_income: 0.4 }} />)
    expect(screen.queryByText(/no measurable contribution/i)).not.toBeInTheDocument()
  })

  it('shows a "Show all" toggle when >20 features, and expands to all', () => {
    render(<FeatureImportance features={rankedRecord(25)} />)
    const toggle = screen.getByRole('button', { name: /show all 25 features/i })
    expect(toggle).toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: /plus an Other bar aggregating 5 more features/i }),
    ).toBeInTheDocument()
    fireEvent.click(toggle)
    expect(screen.getByRole('button', { name: /show fewer/i })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /all 25 grouped features/i })).toBeInTheDocument()
  })

  it('omits the toggle when 20 or fewer features', () => {
    render(<FeatureImportance features={{ credit_score: 0.6, annual_income: 0.4 }} />)
    expect(screen.queryByRole('button', { name: /show all|show fewer/i })).not.toBeInTheDocument()
  })

  it('keeps the synthetic "Other" bar out of the screen-reader feature list', () => {
    render(<FeatureImportance features={rankedRecord(25)} />)
    const srList = screen.getByRole('list', { name: 'Feature importance list' })
    expect(srList.textContent).not.toMatch(/Other \(/)
  })
})
