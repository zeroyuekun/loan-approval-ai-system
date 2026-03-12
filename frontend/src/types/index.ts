export interface User {
  id: number;
  username: string;
  email: string;
  role: 'admin' | 'officer' | 'customer';
  first_name: string;
  last_name: string;
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
  feature_importances: Record<string, number>;
  model_version: string;
  reasoning: string;
  created_at: string;
}

export interface ModelMetrics {
  id: string;
  algorithm: 'rf' | 'xgb';
  version: string;
  accuracy: number;
  precision: number;
  recall: number;
  f1_score: number;
  auc_roc: number;
  confusion_matrix: { tp: number; fp: number; tn: number; fn: number };
  feature_importances: Record<string, number>;
  roc_curve_data: { fpr: number[]; tpr: number[] };
  is_active: boolean;
  created_at: string;
}

export interface GeneratedEmail {
  id: string;
  application: string;
  decision: string;
  subject: string;
  body: string;
  passed_guardrails: boolean;
  attempt_number: number;
  generation_time_ms: number;
  created_at: string;
  guardrail_checks: GuardrailCheck[];
}

export interface GuardrailCheck {
  id: string;
  check_name: string;
  passed: boolean;
  details: string;
}

export interface AgentRun {
  id: string;
  application: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  steps: AgentStep[];
  total_time_ms: number | null;
  error: string;
  created_at: string;
  bias_reports: BiasReport[];
  next_best_offers: NextBestOffer[];
}

export interface AgentStep {
  step_name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  started_at: string;
  completed_at: string | null;
  result_summary: string;
  error: string | null;
}

export interface BiasReport {
  id: string;
  bias_score: number;
  categories: string[];
  analysis: string;
  flagged: boolean;
  requires_human_review: boolean;
  created_at: string;
}

export interface NextBestOffer {
  id: string;
  offers: AlternativeOffer[];
  analysis: string;
  created_at: string;
}

export interface AlternativeOffer {
  type: string;
  amount: number;
  term_months: number;
  estimated_rate: number;
  reasoning: string;
}

export interface TaskStatus {
  task_id: string;
  status: 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE';
  result: any;
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
