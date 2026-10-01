import { formatPercent } from '@/lib/utils'

export const STEP_LABELS: Record<string, string> = {
  fraud_check: 'Fraud Check',
  ml_prediction: 'ML Prediction',
  email_generation: 'Email Generation',
  email_delivery: 'Email Delivery',
  bias_check: 'Bias Check',
  ai_email_review: 'AI Email Review',
  human_escalation: 'Human Escalation',
  human_escalation_severe_bias: 'Human Escalation (Severe Bias)',
  human_escalation_after_retries: 'Human Escalation (After Retries)',
  human_escalation_low_confidence: 'Human Escalation (Low Confidence)',
  human_review_required: 'Human Review Required',
  human_review_approved: 'Human Review Approved',
  human_review_decision: 'Human Review Decision',
  next_best_offers: 'Next Best Offers',
  marketing_message_generation: 'Marketing Message Generation',
  marketing_email_generation: 'Marketing Email Generation',
  marketing_email_delivery: 'Marketing Email Delivery',
  marketing_bias_check: 'Marketing Bias Check',
  marketing_ai_review: 'Marketing AI Review',
  marketing_email_blocked: 'Marketing Email Blocked',
}

// Words that should stay uppercase when auto-capitalising snake_case
const UPPERCASE_WORDS = new Set(['ml', 'ai', 'id', 'payg', 'nbo', 'api', 'afca', 'asic', 'abn', 'tfn'])

function capitaliseWord(word: string): string {
  if (UPPERCASE_WORDS.has(word.toLowerCase())) return word.toUpperCase()
  return word.charAt(0).toUpperCase() + word.slice(1)
}

function humaniseKey(key: string): string {
  return key.split('_').map(capitaliseWord).join(' ')
}

export function formatStepName(name: string | undefined | null): string {
  if (!name) return 'Unknown Step'
  return STEP_LABELS[name] || humaniseKey(name)
}

const RESULT_KEY_LABELS: Record<string, string> = {
  prediction: 'Prediction',
  probability: 'Confidence',
  subject: 'Subject',
  passed_guardrails: 'Guardrails',
  template_fallback: 'Template Fallback',
  flagged: 'Flagged',
  bias_score: 'Bias Score',
  sent: 'Sent',
  recipient: 'Recipient',
  num_offers: 'Offers',
  customer_retention_score: 'Retention Score',
  message_length: 'Message Length',
  generation_time_ms: 'Generation Time',
  attempt_number: 'Attempts',
  reason: 'Reason',
  error: 'Error',
  action: 'Action',
  note: 'Note',
  ml_recommendation: 'ML Recommendation',
  review_category: 'Review Category',
  passed: 'Passed',
  risk_score: 'Risk Score',
  flagged_reasons: 'Flagged Reasons',
}

function formatResultValue(key: string, v: unknown): string {
  if (key === 'prediction' && typeof v === 'string') {
    return v.charAt(0).toUpperCase() + v.slice(1)
  }
  if (typeof v === 'boolean') {
    // Contextual display for booleans; everything else reads Yes/No
    if (key === 'passed_guardrails') return v ? 'Passed' : 'Failed'
    if (key === 'sent') return v ? 'Delivered' : 'Not Sent'
    return v ? 'Yes' : 'No'
  }
  if (typeof v === 'number') {
    if (key === 'probability') return formatPercent(v)
    if (key === 'generation_time_ms') return v < 1000 ? `${v}ms` : `${(v / 1000).toFixed(1)}s`
    if (key === 'message_length') return `${v} chars`
    if (key === 'bias_score' || key === 'customer_retention_score') return `${v}/100`
  }
  return String(v)
}

/** Pretty-print known result_summary keys. Returns label/value pairs. */
export function formatResultSummary(
  summary: string | Record<string, any> | null | undefined
): { label: string; value: string }[] {
  if (!summary) return []
  if (typeof summary === 'string') return [{ label: '', value: summary }]

  return Object.entries(summary)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => ({
      label: RESULT_KEY_LABELS[k] || humaniseKey(k),
      value: formatResultValue(k, v),
    }))
}
