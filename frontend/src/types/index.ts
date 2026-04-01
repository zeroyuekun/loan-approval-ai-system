export interface User {
  id: number;
  username: string;
  email: string;
  role: 'admin' | 'officer' | 'customer';
  first_name: string;
  last_name: string;
  created_at?: string;
}

export interface CustomerProfile {
  id: string;
  is_profile_complete: boolean;
  missing_profile_fields: string[];
  date_of_birth: string | null;
  phone: string;
  address_line_1: string;
  address_line_2: string;
  suburb: string;
  state: string;
  postcode: string;
  marital_status: string;
  residency_status: string;
  primary_id_type: string;
  primary_id_number: string;
  secondary_id_type: string;
  secondary_id_number: string;
  tax_file_number_provided: boolean;
  is_politically_exposed: boolean;
  account_tenure_years: number;
  loyalty_tier: string;
  num_products: number;
  savings_balance: number;
  checking_balance: number;
  has_credit_card: boolean;
  has_mortgage: boolean;
  has_auto_loan: boolean;
  on_time_payment_pct: number;
  previous_loans_repaid: number;

  // Employment
  employer_name: string;
  occupation: string;
  industry: string;
  employment_status: string;
  years_in_current_role: number | null;
  previous_employer: string;

  // Income
  gross_annual_income: number | null;
  other_income: number;
  other_income_source: string;
  partner_annual_income: number | null;

  // Assets
  estimated_property_value: number;
  vehicle_value: number;
  savings_other_institutions: number;
  investment_value: number;
  superannuation_balance: number;

  // Liabilities
  other_loan_repayments_monthly: number;
  other_credit_card_limits: number;
  rent_or_board_monthly: number;

  // Living Situation
  housing_situation: string;
  time_at_current_address_years: number | null;
  number_of_dependants: number;
  previous_suburb: string;
  previous_state: string;
  previous_postcode: string;

  // Contact & Computed
  preferred_contact_method: string;
  total_assets: number;
  total_monthly_liabilities: number;

  created_at: string;
  updated_at: string;
}

export interface StaffCustomerDetail {
  id: string;
  user: User;
  date_of_birth: string | null;
  phone: string;
  address_line_1: string;
  address_line_2: string;
  suburb: string;
  state: string;
  postcode: string;
  marital_status: string;
  residency_status: string;
  primary_id_type: string;
  primary_id_number: string;
  secondary_id_type: string;
  secondary_id_number: string;
  tax_file_number_provided: boolean;
  is_politically_exposed: boolean;
  account_tenure_years: number;
  loyalty_tier: string;
  num_products: number;
  savings_balance: number;
  checking_balance: number;
  has_credit_card: boolean;
  has_mortgage: boolean;
  has_auto_loan: boolean;
  on_time_payment_pct: number;
  previous_loans_repaid: number;

  // Employment
  employer_name: string;
  occupation: string;
  industry: string;
  employment_status: string;
  years_in_current_role: number | null;
  previous_employer: string;

  // Income
  gross_annual_income: number | null;
  other_income: number;
  other_income_source: string;
  partner_annual_income: number | null;

  // Assets
  estimated_property_value: number;
  vehicle_value: number;
  savings_other_institutions: number;
  investment_value: number;
  superannuation_balance: number;

  // Liabilities
  other_loan_repayments_monthly: number;
  other_credit_card_limits: number;
  rent_or_board_monthly: number;

  // Living Situation
  housing_situation: string;
  time_at_current_address_years: number | null;
  number_of_dependants: number;
  previous_suburb: string;
  previous_state: string;
  previous_postcode: string;

  // Contact & Computed
  preferred_contact_method: string;
  total_assets: number;
  total_monthly_liabilities: number;

  created_at: string;
  updated_at: string;
}

export interface LoanApplication {
  id: string;
  applicant: User;
  annual_income: number;
  credit_score: number;
  loan_amount: number;
  loan_term_months: number;
  debt_to_income: number;
  employment_length: number;
  purpose: 'home' | 'auto' | 'education' | 'personal' | 'business';
  home_ownership: 'own' | 'rent' | 'mortgage';
  has_cosigner: boolean;
  property_value: number | null;
  deposit_amount: number | null;
  monthly_expenses: number | null;
  existing_credit_card_limit: number;
  number_of_dependants: number;
  employment_type: 'payg_permanent' | 'payg_casual' | 'self_employed' | 'contract';
  applicant_type: 'single' | 'couple';
  has_hecs?: boolean;
  has_bankruptcy?: boolean;

  // Australian Credit Profile
  credit_utilization_pct?: number | null;
  num_late_payments_24m?: number | null;
  worst_late_payment_days?: number | null;
  num_hardship_flags?: number | null;
  total_credit_limit?: number | null;
  num_credit_providers?: number | null;
  bnpl_active_count?: number | null;
  bnpl_utilization_pct?: number | null;
  bnpl_late_payments_12m?: number | null;
  bnpl_monthly_commitment?: number | null;
  stress_index?: number | null;
  hem_surplus?: number | null;
  debt_service_coverage?: number | null;
  stressed_dsr?: number | null;
  salary_credit_regularity?: number | null;
  income_source_count?: number | null;
  days_negative_balance_90d?: number | null;
  min_balance_30d?: number | null;
  actual_outcome?: string | null;
  months_to_outcome?: number | null;

  status: 'pending' | 'processing' | 'approved' | 'denied' | 'review';
  notes: string;
  conditions: string[];
  conditions_met: boolean;
  created_at: string;
  updated_at: string;
  decision?: LoanDecision;
}

export interface LoanDecision {
  id: string;
  decision: 'approved' | 'denied';
  confidence: number;
  risk_score: number | null;
  feature_importances: Record<string, number> | Array<{ feature: string; importance: number }>;
  shap_values?: Record<string, number>;
  counterfactuals?: Array<string | { feature: string; current: number | string; target: number | string; description?: string }>;
  model_version: string;
  reasoning: string;
  created_at: string;
  denial_reasons?: Array<{ code: string; reason: string; feature: string; contribution: number }>;
  reapplication_guidance?: {
    improvement_targets: Array<{
      feature: string;
      current_value: string;
      target_value: string;
      description: string;
    }>;
    estimated_review_months: number;
    message: string;
  };
}

export interface ModelMetrics {
  id: string;
  algorithm: string;
  version: string;
  accuracy: number | null;
  precision: number | null;
  recall: number | null;
  f1_score: number | null;
  auc_roc: number | null;
  brier_score?: number | null;
  gini_coefficient?: number | null;
  ks_statistic?: number | null;
  log_loss?: number | null;
  ece?: number | null;
  optimal_threshold?: number | null;
  confusion_matrix: {
    true_positives?: number;
    false_positives?: number;
    true_negatives?: number;
    false_negatives?: number;
    tp?: number;
    fp?: number;
    tn?: number;
    fn?: number;
    matrix?: number[][];
  };
  feature_importances: Record<string, number> | Array<{ feature: string; importance: number }>;
  roc_curve_data: { fpr?: number[]; tpr?: number[]; thresholds?: (number | null)[]; auc?: number };
  training_params: Record<string, any>;
  calibration_data?: { fraction_of_positives: number[]; mean_predicted_value: number[]; ece: number; n_bins: number } | null;
  threshold_analysis?: { sweep: Array<{threshold: number; precision: number; recall: number; f1: number; fpr: number; approval_rate: number}>; f1_optimal_threshold: number; youden_j_threshold: number; cost_optimal_threshold: number } | null;
  decile_analysis?: { deciles: Array<{decile: number; count: number; actual_rate: number; cumulative_rate: number; lift: number}> } | null;
  fairness_metrics?: Record<string, any> | null;
  training_metadata?: Record<string, any> | null;
  is_active: boolean;
  created_at: string;
}

export interface GeneratedEmail {
  id: string;
  application_id: string;
  applicant_id?: number;
  applicant_name?: string;
  decision: string;
  subject: string;
  body: string;
  model_used: string;
  passed_guardrails: boolean;
  attempt_number: number;
  generation_time_ms: number;
  created_at: string;
  guardrail_checks: GuardrailCheck[];
}

export interface GuardrailCheck {
  check_name: string;
  passed: boolean;
  details: string;
}

export interface AgentRun {
  id: string;
  application_id: string;
  applicant_id?: number;
  applicant_name?: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'escalated';
  steps: AgentStep[];
  total_time_ms: number | null;
  error: string;
  created_at: string;
  updated_at: string;
  bias_reports: BiasReport[];
  next_best_offers: NextBestOffer[];
  marketing_emails: MarketingEmail[];
}

export interface CustomerActivity {
  customer_id: number;
  customer_name: string;
  emails: GeneratedEmail[];
  agent_runs: AgentRun[];
}

export interface AgentStep {
  step_name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  started_at: string;
  completed_at: string | null;
  result_summary: any;
  error: string | null;
}

export interface BiasReport {
  id: string;
  report_type: 'decision' | 'marketing';
  bias_score: number;
  deterministic_score: number | null;
  score_source: string | null;
  categories: string[];
  analysis: string;
  flagged: boolean;
  requires_human_review: boolean;
  ai_review_approved: boolean | null;
  ai_review_reasoning: string;
  created_at: string;
}

export interface NextBestOffer {
  id: string;
  offers: AlternativeOffer[];
  analysis: string;
  customer_retention_score: number;
  loyalty_factors: string[];
  personalized_message: string;
  marketing_message: string;
  created_at: string;
}

export interface AlternativeOffer {
  type: string;
  name?: string;
  amount: number | null;
  term_months: number | null;
  estimated_rate: number | null;
  benefit?: string;
  reasoning: string;
  monthly_repayment?: number;
  fortnightly_repayment?: number;
  suitability_score?: number;
}

export interface MarketingEmail {
  id: string;
  subject: string;
  body: string;
  passed_guardrails: boolean;
  guardrail_results: GuardrailCheck[];
  generation_time_ms: number;
  attempt_number: number;
  created_at: string;
}

export interface DriftReport {
  id: string
  report_date: string
  psi_score: number
  psi_per_feature: Record<string, number>
  mean_probability: number
  std_probability: number
  approval_rate: number
  drift_detected: boolean
  alert_level: 'none' | 'moderate' | 'significant'
  num_predictions: number
  period_start: string
  period_end: string
}

export interface ModelCard {
  model_details: {
    name: string;
    version: string;
    algorithm: string;
    created_at: string;
    description: string;
  };
  intended_use: {
    primary_use: string;
    users: string;
    out_of_scope: string;
  };
  training_data: {
    description: string;
    size: number;
    features: number;
    label_distribution: Record<string, number>;
  };
  performance_metrics: {
    accuracy: number | null;
    precision: number | null;
    recall: number | null;
    f1_score: number | null;
    auc_roc: number | null;
    gini: number | null;
    brier_score: number | null;
    ece: number | null;
  };
  fairness_analysis: {
    protected_attributes: string[];
    disparate_impact_ratio: Record<string, { disparate_impact_ratio: number; passes_80_percent_rule: boolean }>;
    mitigation: string;
  };
  governance: {
    decision_thresholds: {
      approve: number | null;
      deny: number | null;
      human_review: number | null;
    };
    explainability_method: string;
    next_review_date: string | null;
    retired_at: string | null;
    status: string;
    retraining_policy: Record<string, string | number | boolean>;
  };
  independent_validation: {
    status: string;
    outcome?: string;
    validator?: string;
    validator_role?: string;
    validation_date?: string;
    methodology?: string;
    findings_summary?: string;
    signed_off?: boolean;
    next_validation_due?: string | null;
    note?: string;
  };
  limitations: string[];
  synthetic_data_validation: {
    status: string;
    estimated_real_world_auc?: number | null;
    estimated_auc_range?: [number, number] | null;
    degradation_from_synthetic?: number | null;
    synthetic_confidence_score?: number | null;
    confidence_interpretation?: string;
    methodology?: string;
    references?: string[];
    note?: string;
  };
  regulatory_compliance: Record<string, boolean>;
  last_updated: string;
}

export interface TaskStatus {
  task_id: string;
  status: 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE';
  result: any;
  date_done: string | null;
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
