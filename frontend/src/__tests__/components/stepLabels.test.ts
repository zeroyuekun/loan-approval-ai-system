import { formatStepName, formatResultSummary, STEP_LABELS } from '@/components/agents/stepLabels'

describe('formatStepName', () => {
  it('returns known labels for mapped step names', () => {
    expect(formatStepName('ml_prediction')).toBe('ML Prediction')
    expect(formatStepName('fraud_check')).toBe('Fraud Check')
    expect(formatStepName('bias_check')).toBe('Bias Check')
    expect(formatStepName('email_generation')).toBe('Email Generation')
    expect(formatStepName('next_best_offers')).toBe('Next Best Offers')
  })

  it('auto-capitalises unknown snake_case step names', () => {
    expect(formatStepName('custom_step_name')).toBe('Custom Step Name')
  })

  it('uppercases known acronyms (ML, AI, ID, etc.)', () => {
    expect(formatStepName('ml_model_check')).toBe('ML Model Check')
    expect(formatStepName('ai_review_step')).toBe('AI Review Step')
    expect(formatStepName('check_id_verification')).toBe('Check ID Verification')
  })

  it('returns "Unknown Step" for null/undefined/empty', () => {
    expect(formatStepName(null)).toBe('Unknown Step')
    expect(formatStepName(undefined)).toBe('Unknown Step')
    expect(formatStepName('')).toBe('Unknown Step')
  })

  it('covers all escalation variants', () => {
    expect(formatStepName('human_escalation')).toBe('Human Escalation')
    expect(formatStepName('human_escalation_severe_bias')).toBe('Human Escalation (Severe Bias)')
    expect(formatStepName('human_escalation_after_retries')).toBe('Human Escalation (After Retries)')
    expect(formatStepName('human_escalation_low_confidence')).toBe('Human Escalation (Low Confidence)')
  })
})

describe('formatResultSummary', () => {
  it('returns empty array for null/undefined', () => {
    expect(formatResultSummary(null)).toEqual([])
    expect(formatResultSummary(undefined)).toEqual([])
  })

  it('wraps a plain string in a single entry', () => {
    expect(formatResultSummary('Some result')).toEqual([
      { label: '', value: 'Some result' },
    ])
  })

  it('formats prediction as capitalised', () => {
    const result = formatResultSummary({ prediction: 'approved' })
    expect(result).toContainEqual({ label: 'Prediction', value: 'Approved' })
  })

  it('formats probability as percentage', () => {
    const result = formatResultSummary({ probability: 0.856 })
    expect(result).toContainEqual({ label: 'Confidence', value: '85.6%' })
  })

  it('formats generation_time_ms below 1000 as milliseconds', () => {
    const result = formatResultSummary({ generation_time_ms: 450 })
    expect(result).toContainEqual({ label: 'Generation Time', value: '450ms' })
  })

  it('formats generation_time_ms above 1000 as seconds', () => {
    const result = formatResultSummary({ generation_time_ms: 2500 })
    expect(result).toContainEqual({ label: 'Generation Time', value: '2.5s' })
  })

  it('formats boolean fields contextually', () => {
    const result = formatResultSummary({
      passed_guardrails: true,
      flagged: false,
      sent: true,
      template_fallback: true,
    })
    expect(result).toContainEqual({ label: 'Guardrails', value: 'Passed' })
    expect(result).toContainEqual({ label: 'Flagged', value: 'No' })
    expect(result).toContainEqual({ label: 'Sent', value: 'Delivered' })
    expect(result).toContainEqual({ label: 'Template Fallback', value: 'Yes' })
  })

  it('formats bias_score as /100', () => {
    const result = formatResultSummary({ bias_score: 42 })
    expect(result).toContainEqual({ label: 'Bias Score', value: '42/100' })
  })

  it('formats message_length with chars suffix', () => {
    const result = formatResultSummary({ message_length: 1250 })
    expect(result).toContainEqual({ label: 'Message Length', value: '1250 chars' })
  })

  it('filters out null/undefined/empty values', () => {
    const result = formatResultSummary({
      prediction: 'denied',
      probability: null,
      subject: '',
      bias_score: undefined,
    })
    expect(result).toHaveLength(1)
    expect(result[0].label).toBe('Prediction')
  })

  it('auto-labels unknown keys using capitalisation', () => {
    const result = formatResultSummary({ custom_ml_field: 'test' })
    expect(result).toContainEqual({ label: 'Custom ML Field', value: 'test' })
  })
})

describe('STEP_LABELS', () => {
  it('covers all pipeline steps', () => {
    const expectedSteps = [
      'fraud_check', 'ml_prediction', 'email_generation', 'email_delivery',
      'bias_check', 'next_best_offers', 'marketing_email_generation',
      'marketing_bias_check',
    ]
    for (const step of expectedSteps) {
      expect(STEP_LABELS[step]).toBeDefined()
    }
  })
})
