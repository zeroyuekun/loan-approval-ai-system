/**
 * Build the PATCH body for a customer profile edit form.
 *
 * Only fields that differ from the values the form was seeded with are sent,
 * so a field the server returned as null is never rewritten as '' or 0 just
 * because the form displayed it as blank.
 *
 * ID numbers are write-only on the server (GET returns only a masked copy), so
 * the form never holds the stored value. They are sent only when the user has
 * typed a non-blank value; an untouched or blank field keeps the stored ID.
 */

const ID_NUMBER_FIELDS = new Set(['primary_id_number', 'secondary_id_number'])

// A cleared date or number input means "no value". These fields are nullable
// on the server, so the cleared value goes out as null ('' is not a valid date
// or number).
const BLANK_AS_NULL_FIELDS = new Set([
  'date_of_birth',
  'years_in_current_role',
  'gross_annual_income',
  'other_income',
  'partner_annual_income',
  'time_at_current_address_years',
])

// These are NOT NULL on the server with a default of 0, so null is rejected:
// a cleared input goes out as 0.
const BLANK_AS_ZERO_FIELDS = new Set([
  'estimated_property_value',
  'vehicle_value',
  'savings_other_institutions',
  'investment_value',
  'superannuation_balance',
  'other_loan_repayments_monthly',
  'other_credit_card_limits',
  'rent_or_board_monthly',
  'number_of_dependants',
  'savings_balance',
  'checking_balance',
  'account_tenure_years',
  'num_products',
  'on_time_payment_pct',
  'previous_loans_repaid',
])

function normaliseBlank(key: string, value: unknown): unknown {
  if (value !== '') return value
  if (BLANK_AS_NULL_FIELDS.has(key)) return null
  if (BLANK_AS_ZERO_FIELDS.has(key)) return 0
  return value
}

export function buildProfilePatch<T extends object>(
  initial: Partial<T> | undefined,
  current: Partial<T>,
): Partial<T> {
  const before = (initial ?? {}) as Record<string, unknown>
  const patch: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(current)) {
    if (ID_NUMBER_FIELDS.has(key)) {
      if (typeof value === 'string' && value.trim() !== '') patch[key] = value.trim()
      continue
    }
    if (Object.is(value, before[key])) continue
    const normalised = normaliseBlank(key, value)
    // A blank input over a null server value is not a change.
    if (normalised === null && (before[key] === null || before[key] === undefined)) continue
    patch[key] = normalised
  }
  return patch as Partial<T>
}
