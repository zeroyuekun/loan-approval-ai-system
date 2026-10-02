// Shared choice lists for loan-application categorical fields. Extracted from
// the apply-form steps (components/applications/steps/*.tsx) so the apply
// form and any other form scoring the same fields (e.g. the Model Metrics
// "Try it" tab) read from one definition instead of duplicating option text
// that could drift out of sync with backend choices
// (backend/apps/loans/models.py LoanApplication).

export interface FieldOption {
  value: string
  label: string
}

export const APPLICANT_TYPE_OPTIONS: FieldOption[] = [
  { value: 'single', label: 'Single Applicant' },
  { value: 'couple', label: 'Joint Applicants (Couple)' },
]

export const HOME_OWNERSHIP_OPTIONS: FieldOption[] = [
  { value: 'own', label: 'Own Outright' },
  { value: 'mortgage', label: 'Own with Mortgage' },
  { value: 'rent', label: 'Renting' },
]

export const EMPLOYMENT_TYPE_OPTIONS: FieldOption[] = [
  { value: 'payg_permanent', label: 'PAYG Full-Time/Permanent' },
  { value: 'payg_casual', label: 'PAYG Casual' },
  { value: 'self_employed', label: 'Self-Employed (ABN)' },
  { value: 'contract', label: 'Fixed-Term Contract' },
]

export const PURPOSE_OPTIONS: FieldOption[] = [
  { value: 'home', label: 'Home Purchase / Refinance' },
  { value: 'auto', label: 'Vehicle Loan' },
  { value: 'education', label: 'Education (non-HECS)' },
  { value: 'personal', label: 'Personal Loan' },
  { value: 'business', label: 'Business Loan' },
]

export const LOAN_TERM_OPTIONS: FieldOption[] = [
  { value: '12', label: '12 months (1 year)' },
  { value: '24', label: '24 months (2 years)' },
  { value: '36', label: '36 months (3 years)' },
  { value: '60', label: '60 months (5 years)' },
  { value: '84', label: '84 months (7 years)' },
  { value: '240', label: '240 months (20 years)' },
  { value: '300', label: '300 months (25 years)' },
  { value: '360', label: '360 months (30 years)' },
]

// Not currently collected on the apply form; mirrors
// LoanApplication.AustralianState choices (backend/apps/loans/models.py).
export const AU_STATE_OPTIONS: FieldOption[] = [
  { value: 'NSW', label: 'New South Wales' },
  { value: 'VIC', label: 'Victoria' },
  { value: 'QLD', label: 'Queensland' },
  { value: 'WA', label: 'Western Australia' },
  { value: 'SA', label: 'South Australia' },
  { value: 'TAS', label: 'Tasmania' },
  { value: 'ACT', label: 'Australian Capital Territory' },
  { value: 'NT', label: 'Northern Territory' },
]
