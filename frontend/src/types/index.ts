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
  status: 'pending' | 'processing' | 'approved' | 'denied' | 'review';
  notes: string;
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
  counterfactuals?: Array<string | { feature: string; current: number | string; target: number | string; description?: string }>;
  model_version: string;
  reasoning: string;
  created_at: string;
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
