import { render, screen } from '@testing-library/react'
import { GovernanceTab } from '@/components/model-health/GovernanceTab'
import type { ModelCard } from '@/types'

const card: ModelCard = {
  model_details: { name: 'XGBoost Loan Approval', algorithm: 'xgb', version: '3', created_at: '2026-01-01', description: 'AU loan approval ensemble' },
  intended_use: { primary_use: 'Personal / home / auto loan approval', users: 'Loan officers', out_of_scope: 'Wholesale or commercial lending' },
  training_data: { description: 'Synthetic AU lending data', size: 10000, features: 71, label_distribution: { approved: 0.55, denied: 0.45 } },
  performance_metrics: { accuracy: 0.87, precision: 0.85, recall: 0.82, f1_score: 0.84, auc_roc: 0.91, gini: 0.82, brier_score: 0.12, ece: 0.04 },
  fairness_analysis: { protected_attributes: ['gender', 'age_bucket'], mitigation: 'Pre-deployment four-fifths gate', disparate_impact_ratio: {} },
  governance: { status: 'active', decision_thresholds: { approve: 0.7, deny: 0.3, human_review: 0.5 }, explainability_method: 'shap_tree', next_review_date: '2026-12-01', retraining_policy: {} },
  independent_validation: { status: 'not_validated', note: 'Pending independent validation' },
  limitations: ['Training data is synthetic', 'No CDR integration in this build'],
  synthetic_data_validation: { status: 'available', estimated_real_world_auc: 0.82, estimated_auc_range: [0.78, 0.86], degradation_from_synthetic: 0.09, synthetic_confidence_score: 0.7, confidence_interpretation: 'Moderate', note: 'TSTR estimate' },
  regulatory_compliance: { apra_cpg_235: true, nccp_act: true, banking_code: true },
  last_updated: '2026-05-25T00:00:00Z',
} as unknown as ModelCard

describe('GovernanceTab', () => {
  it('renders intended use section', () => {
    render(<GovernanceTab card={card} />)
    expect(screen.getByText(/intended use/i)).toBeInTheDocument()
    expect(screen.getByText(/Loan officers/i)).toBeInTheDocument()
  })

  it('renders training data summary with dataset size', () => {
    render(<GovernanceTab card={card} />)
    expect(screen.getByRole('heading', { name: /training data/i })).toBeInTheDocument()
    expect(screen.getByText('10,000')).toBeInTheDocument()
  })

  it('renders regulatory compliance checklist', () => {
    render(<GovernanceTab card={card} />)
    expect(screen.getByText(/APRA CPG 235/i)).toBeInTheDocument()
    expect(screen.getByText(/NCCP Act/i)).toBeInTheDocument()
    expect(screen.getByText(/Banking Code/i)).toBeInTheDocument()
  })

  it('renders limitations list', () => {
    render(<GovernanceTab card={card} />)
    expect(screen.getByText(/Training data is synthetic/)).toBeInTheDocument()
    expect(screen.getByText(/No CDR integration in this build/)).toBeInTheDocument()
  })

  it('renders empty state when card is null', () => {
    render(<GovernanceTab card={null} />)
    expect(screen.getByText(/no governance data/i)).toBeInTheDocument()
  })
})
