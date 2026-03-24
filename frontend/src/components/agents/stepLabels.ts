export const STEP_LABELS: Record<string, string> = {
  ml_prediction: 'ML Prediction',
  email_generation: 'Email Generation',
  email_delivery: 'Email Delivery',
  bias_check: 'Bias Check',
  ai_email_review: 'AI Email Review',
  human_escalation: 'Human Escalation',
  human_escalation_severe_bias: 'Human Escalation (Severe Bias)',
  human_escalation_after_retries: 'Human Escalation (After Retries)',
  human_escalation_low_confidence: 'Human Escalation (Low Confidence)',
  next_best_offers: 'Next Best Offers',
  marketing_message_generation: 'Marketing Message Generation',
  marketing_email_generation: 'Marketing Email Generation',
  marketing_email_delivery: 'Marketing Email Delivery',
  marketing_bias_check: 'Marketing Bias Check',
  marketing_ai_review: 'Marketing AI Review',
  marketing_email_blocked: 'Marketing Email Blocked',
  human_review_approved: 'Human Review Approved',
  human_review_decision: 'Human Review Decision',
}

// Words that should stay uppercase when auto-capitalising snake_case
const UPPERCASE_WORDS = new Set(['ml', 'ai', 'id', 'payg', 'nbo', 'api', 'afca', 'asic', 'abn', 'tfn'])

function capitaliseWord(word: string): string {
  if (UPPERCASE_WORDS.has(word.toLowerCase())) return word.toUpperCase()
  return word.charAt(0).toUpperCase() + word.slice(1)
}

export function formatStepName(name: string): string {
  if (STEP_LABELS[name]) return STEP_LABELS[name]
  return name.split('_').map(capitaliseWord).join(' ')
}

/** Pretty-print known result_summary keys. Returns label/value pairs. */
export function formatResultSummary(
  summary: string | Record<string, any> | null | undefined
): { label: string; value: string }[] {
  if (!summary) return []
  if (typeof summary === 'string') return [{ label: '', value: summary }]

  const KEY_LABELS: Record<string, string> = {
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
  }

  return Object.entries(summary)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => {
      const label = KEY_LABELS[k] || k.split('_').map(capitaliseWord).join(' ')

      let value: string
      if (k === 'prediction' && typeof v === 'string') {
        value = v.charAt(0).toUpperCase() + v.slice(1)
      } else if (typeof v === 'boolean') {
        // Contextual display for booleans
        if (k === 'passed_guardrails') value = v ? 'Passed' : 'Failed'
        else if (k === 'flagged') value = v ? 'Yes' : 'No'
        else if (k === 'sent') value = v ? 'Delivered' : 'Not Sent'
        else if (k === 'template_fallback') value = v ? 'Yes' : 'No'
        else value = v ? 'Yes' : 'No'
      } else if (k === 'probability' && typeof v === 'number') {
        value = `${(v * 100).toFixed(1)}%`
      } else if (k === 'generation_time_ms' && typeof v === 'number') {
        value = v < 1000 ? `${v}ms` : `${(v / 1000).toFixed(1)}s`
      } else if (k === 'message_length' && typeof v === 'number') {
        value = `${v} chars`
      } else if (k === 'bias_score' && typeof v === 'number') {
        value = `${v}/100`
      } else if (k === 'customer_retention_score' && typeof v === 'number') {
        value = `${v}/100`
      } else {
        value = String(v)
      }

      return { label, value }
    })
}
