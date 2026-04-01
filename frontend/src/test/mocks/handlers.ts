import { http, HttpResponse } from 'msw'

const API_URL = 'http://localhost:8000/api/v1'

const mockUser = {
  id: 1,
  username: 'testuser',
  email: 'test@example.com',
  role: 'admin' as const,
  first_name: 'Test',
  last_name: 'User',
}

const mockCustomerUser = {
  id: 2,
  username: 'customer1',
  email: 'customer@example.com',
  role: 'customer' as const,
  first_name: 'Jane',
  last_name: 'Doe',
}

const mockCustomerProfile = {
  id: 'cp-1',
  is_profile_complete: true,
  missing_profile_fields: [],
  date_of_birth: '1990-01-15',
  phone: '0412345678',
  address_line_1: '123 Test St',
  address_line_2: '',
  suburb: 'Sydney',
  state: 'NSW',
  postcode: '2000',
  marital_status: 'single',
  residency_status: 'citizen',
  primary_id_type: 'drivers_licence',
  primary_id_number: 'DL123456',
  secondary_id_type: 'passport',
  secondary_id_number: 'PA789012',
  tax_file_number_provided: true,
  is_politically_exposed: false,
  account_tenure_years: 3,
  loyalty_tier: 'gold',
  num_products: 2,
  savings_balance: 15000,
  checking_balance: 5000,
  has_credit_card: true,
  has_mortgage: false,
  has_auto_loan: false,
  on_time_payment_pct: 98,
  previous_loans_repaid: 1,
  employer_name: 'Test Corp',
  occupation: 'Engineer',
  industry: 'Technology',
  employment_status: 'full_time',
  years_in_current_role: 3,
  previous_employer: 'Old Corp',
  gross_annual_income: 95000,
  other_income: 0,
  other_income_source: '',
  partner_annual_income: null,
  estimated_property_value: 0,
  vehicle_value: 20000,
  savings_other_institutions: 5000,
  investment_value: 10000,
  superannuation_balance: 50000,
  other_loan_repayments_monthly: 0,
  other_credit_card_limits: 5000,
  rent_or_board_monthly: 1800,
  housing_situation: 'renting',
  time_at_current_address_years: 2,
  number_of_dependants: 0,
  previous_suburb: '',
  previous_state: '',
  previous_postcode: '',
  preferred_contact_method: 'email',
  total_assets: 100000,
  total_monthly_liabilities: 1800,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-06-01T00:00:00Z',
}

const mockLoanApplication = {
  id: 'loan-1',
  applicant: mockUser,
  annual_income: 85000,
  credit_score: 750,
  loan_amount: 25000,
  loan_term_months: 36,
  debt_to_income: 2.5,
  employment_length: 5,
  purpose: 'personal' as const,
  home_ownership: 'rent' as const,
  has_cosigner: false,
  property_value: null,
  deposit_amount: null,
  monthly_expenses: 3000,
  existing_credit_card_limit: 5000,
  number_of_dependants: 0,
  employment_type: 'payg_permanent' as const,
  applicant_type: 'single' as const,
  status: 'pending' as const,
  notes: '',
  created_at: '2024-06-01T00:00:00Z',
  updated_at: '2024-06-01T00:00:00Z',
}

export const handlers = [
  // Auth: CSRF token
  http.get(`${API_URL}/auth/csrf/`, () => {
    return HttpResponse.json({ detail: 'CSRF cookie set' })
  }),

  // Auth: Login
  http.post(`${API_URL}/auth/login/`, () => {
    return HttpResponse.json({
      user: mockUser,
      detail: 'Login successful',
    })
  }),

  // Auth: Logout
  http.post(`${API_URL}/auth/logout/`, () => {
    return HttpResponse.json({ detail: 'Logged out' })
  }),

  // Auth: Profile
  http.get(`${API_URL}/auth/me/`, () => {
    return HttpResponse.json(mockUser)
  }),

  // Auth: Customer profile
  http.get(`${API_URL}/auth/me/profile/`, () => {
    return HttpResponse.json(mockCustomerProfile)
  }),

  // Auth: Token refresh
  http.post(`${API_URL}/auth/refresh/`, () => {
    return HttpResponse.json({ detail: 'Token refreshed' })
  }),

  // Loans: Create
  http.post(`${API_URL}/loans/`, () => {
    return HttpResponse.json(mockLoanApplication, { status: 201 })
  }),

  // Loans: List
  http.get(`${API_URL}/loans/`, () => {
    return HttpResponse.json({
      count: 1,
      next: null,
      previous: null,
      results: [mockLoanApplication],
    })
  }),

  // Loans: Get
  http.get(`${API_URL}/loans/:id/`, () => {
    return HttpResponse.json(mockLoanApplication)
  }),
]

export { mockUser, mockCustomerUser, mockCustomerProfile, mockLoanApplication }
