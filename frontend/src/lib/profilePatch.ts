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

// Fields the server stores as a date or number: a cleared input means "no
// value" and is sent as null, because '' is not a valid date or number.
const BLANK_AS_NULL_FIELDS = new Set([
  'date_of_birth',
  'years_in_current_role',
  'gross_annual_income',
  'other_income',
  'partner_annual_income',
  'estimated_property_value',
  'vehicle_value',
  'savings_other_institutions',
  'investment_value',
  'superannuation_balance',
  'other_loan_repayments_monthly',
  'other_credit_card_limits',
  'rent_or_board_monthly',
  'time_at_current_address_years',
  'number_of_dependants',
  'savings_balance',
  'checking_balance',
  'account_tenure_years',
  'num_products',
  'on_time_payment_pct',
  'previous_loans_repaid',
])

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
    const normalised = value === '' && BLANK_AS_NULL_FIELDS.has(key) ? null : value
    // A blank input over a null server value is not a change.
    if (normalised === null && (before[key] === null || before[key] === undefined)) continue
    patch[key] = normalised
  }
  return patch as Partial<T>
}
