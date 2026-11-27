import { describeSubmitError } from '@/hooks/useApplicationForm'

describe('describeSubmitError', () => {
  it('names the field the server rejected instead of a generic retry message', () => {
    const error = { response: { data: { employment_length: ['A valid integer is required.'] } } }
    expect(describeSubmitError(error)).toBe('Time in current role: A valid integer is required.')
  })

  it('uses the server detail message when there is one', () => {
    const error = { response: { data: { detail: 'Please complete your profile first.' } } }
    expect(describeSubmitError(error)).toBe('Please complete your profile first.')
  })

  it('shows non-field errors without a label', () => {
    const error = { response: { data: { non_field_errors: ['Deposit exceeds property value.'] } } }
    expect(describeSubmitError(error)).toBe('Deposit exceeds property value.')
  })

  it('falls back to a generic message for network errors', () => {
    expect(describeSubmitError(new Error('Network Error'))).toBe('Failed to submit application. Please try again.')
  })
})
